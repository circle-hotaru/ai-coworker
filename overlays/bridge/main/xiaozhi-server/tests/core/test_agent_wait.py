import asyncio
import json
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.connection import ConnectionHandler
from core.utils.agent_wait import (AgentWait, agent_is_waiting, monitor_agent,
                                  stop_agent_monitor, submit_agent_chat)

class Tests(unittest.IsolatedAsyncioTestCase):
    def conn(self):
        return SimpleNamespace(config={'agent_wait': {'heartbeat_seconds': .02,
            'notice_seconds': .03, 'task_timeout_seconds': .07}},
            websocket=SimpleNamespace(send=AsyncMock()), session_id='test',
            stop_event=threading.Event(), logger=Mock(), last_activity_time=0)

    async def test_heartbeats_soft_timeout_then_original_result(self):
        c = self.conn()
        done = threading.Event()
        c.executor = ThreadPoolExecutor(max_workers=1)
        c.chat = Mock(side_effect=lambda text: done.wait(2))
        try:
            future = submit_agent_chat(c, 'one request')
            await asyncio.sleep(.12)
            self.assertTrue(agent_is_waiting(c))
            messages = [json.loads(call.args[0]) for call in c.websocket.send.call_args_list]
            self.assertGreaterEqual(sum(m['type']=='llm' for m in messages), 3)
            notices = [m for m in messages if m['type']=='tts']
            self.assertEqual(len(notices), 2)
            self.assertIn('超过预计等待时间', notices[-1]['text'])
            self.assertTrue(all(m['state']=='sentence_start' for m in notices))
            c.chat.assert_called_once_with('one request')
            self.assertFalse(future.done())  # Soft deadline never cancels or retries.
            done.set()
            await asyncio.wrap_future(future)
            await c.agent_wait.monitor
            self.assertFalse(agent_is_waiting(c))
            self.assertGreater(c.last_activity_time, 0)
            before = c.websocket.send.call_count
            await asyncio.sleep(.04)
            self.assertEqual(c.websocket.send.call_count, before)
        finally:
            done.set()
            stop_agent_monitor(c)
            c.executor.shutdown(wait=True)

    async def test_streaming_output_suppresses_early_notice_but_not_soft_timeout(self):
        c = self.conn(); wait = AgentWait(); wait.output_started.set()
        task = asyncio.create_task(monitor_agent(c, wait))
        await asyncio.sleep(.1)
        wait.done.set(); await task
        messages = [json.loads(call.args[0]) for call in c.websocket.send.call_args_list]
        self.assertTrue(messages)
        notices = [m for m in messages if m['type']=='tts']
        self.assertEqual(len(notices), 1)
        self.assertIn('超过预计等待时间', notices[0]['text'])

    async def test_disconnect_cancels_monitor_not_remote_work(self):
        c = self.conn(); c.agent_wait = AgentWait()
        c.agent_wait.monitor = asyncio.create_task(monitor_agent(c, c.agent_wait))
        stop_agent_monitor(c)
        await asyncio.gather(c.agent_wait.monitor, return_exceptions=True)
        self.assertTrue(agent_is_waiting(c))
        self.assertFalse(c.agent_wait.done.is_set())

    async def test_real_idle_checker_pauses_only_during_agent_work(self):
        c = ConnectionHandler.__new__(ConnectionHandler)
        c.stop_event = threading.Event(); c.agent_wait = AgentWait()
        c.last_activity_time = (time.time()-100)*1000
        c.need_bind = False; c.timeout_seconds = 1
        c.logger = Mock(); c.websocket = object()
        async def close(ws): c.stop_event.set()
        c.close = AsyncMock(side_effect=close)
        sleep = asyncio.sleep
        async def short_sleep(seconds): await sleep(.005)
        with patch('core.connection.asyncio.sleep', short_sleep):
            task = asyncio.create_task(c._check_timeout())
            await sleep(.025)
            c.close.assert_not_called()
            c.agent_wait.done.set()
            await asyncio.wait_for(task, 1)
        c.close.assert_awaited_once_with(c.websocket)

if __name__ == '__main__': unittest.main()
