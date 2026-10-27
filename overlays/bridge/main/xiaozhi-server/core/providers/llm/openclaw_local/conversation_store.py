"""Persist each board's active task, rotating only on explicit new-task intent."""
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_NEW_TASK = re.compile(r'^(?:请)?(?:(?:开始|开启|创建)(?:一个)?)?新任务(?:[，,。.:：！？!?\s]+|(?=帮我|请|给我)|$)(.*)$', re.S)
_LOCK = threading.RLock()

class ConversationStore:
    def __init__(self, path):
        self.path = Path(path)

    def select(self, device_id, agent_id, prefix, text):
        match = _NEW_TASK.fullmatch(text.strip())
        new_task = match is not None
        body = match.group(1).strip() if match else text
        key = device_id + '|' + agent_id
        with _LOCK:
            state = json.loads(self.path.read_text()) if self.path.exists() else {'version': 1, 'devices': {}}
            entry = state['devices'].get(key)
            if entry is None or new_task:
                stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')
                entry = {'conversation_id': f'{prefix}-task-{stamp}-{uuid.uuid4().hex}'}
                state['devices'][key] = entry
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_name(self.path.name + '.tmp-' + uuid.uuid4().hex)
                try:
                    with temp.open('x') as f:
                        temp.chmod(0o600)
                        json.dump(state, f, ensure_ascii=False, indent=2)
                    temp.replace(self.path)
                finally:
                    temp.unlink(missing_ok=True)
            return entry['conversation_id'], body, new_task
