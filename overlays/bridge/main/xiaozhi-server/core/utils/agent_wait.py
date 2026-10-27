"""Keep the device alive while one original OpenClaw request is running.

The task threshold is a soft deadline: it reports progress, never retries or
claims to cancel the remote task. The HTTP provider owns transport timeouts.
"""
import asyncio
import json
import threading
import time
from dataclasses import dataclass, field


@dataclass
class AgentWait:
    started: float = field(default_factory=time.monotonic)
    done: threading.Event = field(default_factory=threading.Event)
    output_started: threading.Event = field(default_factory=threading.Event)
    monitor: object = None


def agent_is_waiting(conn):
    wait = getattr(conn, 'agent_wait', None)
    return wait is not None and not wait.done.is_set()


def stop_agent_monitor(conn):
    wait = getattr(conn, 'agent_wait', None)
    if wait is not None and wait.monitor is not None:
        wait.monitor.cancel()


def submit_agent_chat(conn, text):
    stop_agent_monitor(conn)
    wait = AgentWait()
    conn.agent_wait = wait

    def run():
        try:
            return conn.chat(text)
        finally:
            wait.done.set()
            # Resume ordinary idle accounting from task completion, not submission.
            conn.last_activity_time = time.time() * 1000

    try:
        future = conn.executor.submit(run)
    except Exception:
        wait.done.set()
        raise
    wait.monitor = asyncio.create_task(monitor_agent(conn, wait))
    return future


async def monitor_agent(conn, wait):
    settings = conn.config.get('agent_wait', {})
    heartbeat = max(0.01, float(settings.get('heartbeat_seconds', 20)))
    notice_after = float(settings.get('notice_seconds', 30))
    task_timeout = float(settings.get('task_timeout_seconds', 600))
    notice_sent = timeout_sent = False
    next_heartbeat = wait.started + heartbeat
    try:
        while not wait.done.is_set() and not conn.stop_event.is_set():
            deadlines = [next_heartbeat]
            if not wait.output_started.is_set():
                if not notice_sent:
                    deadlines.append(wait.started + notice_after)
            if not timeout_sent:
                deadlines.append(wait.started + task_timeout)
            await asyncio.sleep(max(0.01, min(deadlines) - time.monotonic()))
            if wait.done.is_set() or conn.stop_event.is_set():
                break
            # Existing firmware accepts llm messages without an emotion. Any
            # application frame refreshes its last_incoming_time; no state change.
            now = time.monotonic()
            if now >= next_heartbeat:
                await conn.websocket.send(json.dumps({
                    'type': 'llm', 'heartbeat': True, 'session_id': conn.session_id,
                }))
                next_heartbeat = now + heartbeat
            elapsed = time.monotonic() - wait.started
            text = None
            if elapsed >= task_timeout and not timeout_sent:
                text = '仍在处理，已超过预计等待时间，请勿重复提交；完成后会继续回复。'
                timeout_sent = notice_sent = True
            elif not wait.output_started.is_set() and elapsed >= notice_after and not notice_sent:
                text = '仍在处理，请稍候，无需重复提交。'
                notice_sent = True
            if text is not None:
                # A subtitle only: never emit TTS stop/LAST or reopen capture.
                await conn.websocket.send(json.dumps({
                    'type': 'tts', 'state': 'sentence_start', 'text': text,
                    'session_id': conn.session_id,
                }, ensure_ascii=False))
    except asyncio.CancelledError:
        raise
    except Exception:
        # A broken client channel does not mean the remote task was cancelled.
        conn.logger.warning('Agent waiting heartbeat stopped: device channel unavailable')
