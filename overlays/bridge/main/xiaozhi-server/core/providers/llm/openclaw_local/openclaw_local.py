"""Delegate voice turns to the local OpenClaw agent, including its tools."""
import copy
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from ruamel.yaml import YAML
import openai
import httpx
from core.providers.llm.base import LLMProviderBase
from .conversation_store import ConversationStore
from core.utils.push_store import PushStore, DEVICE_AGENTS
from core.utils.device_registry import configure_devices

class LLMProvider(LLMProviderBase):
    is_local_agent = True
    def __init__(self, config):
        # A timeout must never replay a tool-bearing request automatically.
        self.client = openai.OpenAI(base_url=config['base_url'], api_key=config['api_key'],
                                    timeout=httpx.Timeout(float(config.get('timeout', 1800)), connect=5.0),
                                    max_retries=0)
        self.model = config.get('model_name', 'openclaw/main')
        self.device_map = Path(config['device_map'])
        self.route = None
        self.voice_instruction = config.get('voice_instruction', '请用简洁自然的中文回答，适合语音播放。需要执行任务时使用真实工具，失败时如实说明。')
        configure_devices(self.device_map)
        self.conversations = ConversationStore(self.device_map.with_name("conversation-state.json"))

    def for_device(self, device_id):
        # A separate binding per connection avoids cross-device routing races.
        with self.device_map.open() as f:
            mapping = YAML(typ='safe').load(f)
        routes = {str(k).strip().lower(): v for k, v in mapping['devices'].items()}
        route = routes.get(str(device_id or '').strip().lower())
        if not route:
            raise ValueError('Device is not registered')
        for key in ('name', 'agent_id', 'conversation_id'):
            if not isinstance(route.get(key), str) or not route[key].strip():
                raise ValueError('Invalid device route: ' + key)
        bound = copy.copy(self)
        bound.route = dict(route)
        bound.device_id = str(device_id).strip().lower()
        bound.model = 'openclaw/' + route['agent_id']
        return bound

    def response(self, session_id, dialogue, **kwargs):
        if self.route is None:
            raise RuntimeError('Device route has not been bound')
        # OpenClaw owns history. Do not re-submit old requests as new work.
        latest = next((m for m in reversed(dialogue) if m.get('role') == 'user'), None)
        if not latest:
            return
        instruction = {'role': 'system', 'content': self.voice_instruction}
        conversation_id = self.route['conversation_id']
        user_text = latest.get('content', '')
        if self.route.get('session_mode') == 'explicit_new_task':
            conversation_id, user_text, new_task = self.conversations.select(
                self.device_id, self.route['agent_id'], conversation_id, user_text)
            if new_task and not user_text:
                user_text = '新任务。请只确认新会话已创建，提醒我再次按 BOOT 后说出任务。'
        elif self.route.get('session_mode') == 'per_task':
            timestamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')
            conversation_id = f"{conversation_id}-task-{timestamp}-{uuid.uuid4().hex}"
        push = None
        if getattr(self, 'device_id', '') in DEVICE_AGENTS and self.route.get('agent_id') == DEVICE_AGENTS[self.device_id]:
            push = PushStore(self.device_map.with_name('push-state.sqlite'))
            push_session = push.enroll(conversation_id, self.device_id)
        stream = None
        primary_run = None
        spoken = []
        try:
            stream = self.client.chat.completions.create(model=self.model,
                user=conversation_id,
                messages=[instruction, {'role':'user', 'content':user_text}], stream=True)
            for chunk in stream:
                primary_run = getattr(chunk, 'id', None) or primary_run
                if chunk.choices and chunk.choices[0].delta.content:
                    spoken.append(chunk.choices[0].delta.content)
                    yield chunk.choices[0].delta.content
        except (openai.APIConnectionError, httpx.TransportError):
            # The gateway may still be executing tools after this transport is lost.
            yield '等待回复的连接已中断，任务可能仍在后台处理。请勿重复提交，请在 OpenClaw 中查看进度。'
        finally:
            if push is not None:
                push.complete_primary(push_session, primary_run, ''.join(spoken))
            if stream is not None:
                stream.close()
