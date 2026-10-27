"""Run offline extension tests in disposable materialized source workspaces."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
server = ROOT / '.build/bridge/main/xiaozhi-server'
firmware = ROOT / '.build/firmware'
config = server / 'data/.config.yaml'
if not (server / 'app.py').is_file() or not (firmware / 'scripts/tests').is_dir():
    raise SystemExit('Materialize bridge and firmware first')
if config.exists():
    raise SystemExit('Tests require an unconfigured disposable bridge workspace, without data/.config.yaml')
config.parent.mkdir(exist_ok=True)
# Exclusive private creation prevents accidental overwrite of a user's runtime config.
fd = os.open(config, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write('selected_module:\n  LLM: OpenClawLocal\nLLM:\n  OpenClawLocal:\n    type: openclaw_local\n')
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['AI_COWORKER_AGENTS'] = 'reviewer,researcher,operator'
env['AI_COWORKER_DANCE_AGENT'] = 'operator'
env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
# Host tests use temporary Git repos; do not inherit global commit signing requirements.
env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='commit.gpgsign', GIT_CONFIG_VALUE_0='false')
commands = []
for p in sorted((ROOT / 'overlays/bridge/main/xiaozhi-server/tests').rglob('test_*.py')):
    rel = p.relative_to(ROOT / 'overlays/bridge/main/xiaozhi-server')
    commands.append((server, [sys.executable, '-m', 'unittest', 'discover', '-s', str(rel.parent), '-p', p.name]))
commands += [
    (server, [sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'integrations/xunfei-asr'), '-p', 'test_manage.py']),
    (firmware, [sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/tests']),
    (ROOT, ['node', 'integrations/openclaw-agent-voice-push/test.mjs']),
    (ROOT, ['node', 'integrations/openclaw-agent-voice-push/test-collaboration.mjs']),
    (ROOT, ['node', '--test', 'integrations/openclaw-stackchan-dance/index.test.js']),
    (ROOT, [sys.executable, 'scripts/check_public.py']),
]
try:
    for cwd, command in commands:
        subprocess.run(command, cwd=cwd, env=env, check=True)
finally:
    config.unlink()
