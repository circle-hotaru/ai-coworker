"""Prepare/probe/switch ASR without exposing credentials or changing other modules."""
import argparse
import asyncio
import base64
import copy
import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import wave
import yaml
from ruamel.yaml import YAML

REPO = Path(__file__).resolve().parents[2]
SERVER = Path(os.environ.get('AI_COWORKER_SERVER', str(REPO / '.build/bridge/main/xiaozhi-server'))).expanduser().resolve()
PRIVATE = Path(os.environ.get('AI_COWORKER_PRIVATE', str(REPO / 'runtime/xunfei'))).expanduser().resolve()
CONFIG = SERVER / 'data/.config.yaml'
STATE = PRIVATE / 'switch-state.json'
sys.path.insert(0, str(SERVER))

def candidate(credentials):
    keys = yaml.safe_load(credentials.read_text()) or {}
    for key in ('app_id', 'api_key', 'api_secret'):
        value = keys.get(key)
        if not isinstance(value, str) or not value.strip() or value.startswith('你的'):
            raise ValueError(f'请先在本地密钥文件填写 {key}；当前 ASR 未改变')
    template = yaml.safe_load((Path(__file__).parent / 'config.example.yaml').read_text())
    settings = template['ASR']['XunfeiStreamASR']
    settings.update({key: keys[key].strip() for key in ('app_id', 'api_key', 'api_secret')})
    return settings

def load_provider():
    # The server's synchronous logger/config bootstrap uses asyncio.run().
    # Import outside the probe's event loop without changing server-wide startup.
    from core.providers.asr.xunfei_stream import ASRProvider
    return ASRProvider

async def probe(settings, audio):
    import websockets
    with wave.open(str(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('测试文件必须为 16kHz/16bit/单声道 WAV')
        pcm = wav.readframes(wav.getnframes())
    if not pcm or len(pcm) > 16000 * 2 * 60:
        raise ValueError('音频必须非空且不超过60秒')
    ASRProvider = await asyncio.to_thread(load_provider)
    p = ASRProvider(settings, True)
    async def exchange():
        async with websockets.connect(p.create_url(), open_timeout=10, close_timeout=2) as ws:
            p.asr_ws = ws
            async def send():
                for offset in range(0, len(pcm), 1280):
                    await p._send_audio_frame(pcm[offset:offset+1280], 0 if offset == 0 else 1)
                    await asyncio.sleep(0.04)
                await p._send_audio_frame(b'', 2)
            sender = asyncio.create_task(send())
            try:
                async for raw in ws:
                    response = json.loads(raw)
                    header = response.get('header', {})
                    if header.get('code', 0):
                        raise ValueError(f"讯飞返回错误码 {header['code']}（检查服务权限/密钥/额度）")
                    result = response.get('payload', {}).get('result', {})
                    if result.get('text'):
                        decoded = json.loads(base64.b64decode(result['text']))
                        if decoded.get('ret', 0):
                            raise ValueError(f"讯飞识别错误码 {decoded['ret']}")
                        p._merge_result(decoded, result)
                    if header.get('status') == 2 or result.get('status') == 2:
                        if not p.text.strip(): raise ValueError('没有识别到文字，未切换 ASR')
                        return p.text
                raise ValueError('未收到最终识别结果，未切换 ASR')
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
    return await asyncio.wait_for(exchange(), timeout=len(pcm)/32000 + 20)

def apply(settings):
    if STATE.exists(): raise ValueError('已有切换记录；请先回滚，避免覆盖恢复记录')
    y = YAML(); original = y.load(CONFIG.read_text())
    PRIVATE.mkdir(parents=True, exist_ok=True); PRIVATE.chmod(0o700)
    backup = PRIVATE / ('config-before-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.yaml')
    shutil.copy2(CONFIG, backup); backup.chmod(0o600)
    changed = copy.deepcopy(original)
    changed.setdefault('selected_module', {})['ASR'] = 'XunfeiStreamASR'
    changed.setdefault('ASR', {})['XunfeiStreamASR'] = settings
    temp = PRIVATE / 'config-pending.yaml'
    with temp.open('w') as f: y.dump(changed, f)
    temp.chmod(0o600)
    state = {'backup': str(backup), 'previous_asr': original.get('selected_module', {}).get('ASR'), 'status': 'prepared'}
    STATE.write_text(json.dumps(state, indent=2)+'\n'); STATE.chmod(0o600)
    os.replace(temp, CONFIG)
    print('ASR 配置已切为 XunfeiStreamASR/V2.0；需要重启语音桥生效')

def rollback():
    state = json.loads(STATE.read_text()); y = YAML()
    before = y.load(Path(state['backup']).read_text()); current = y.load(CONFIG.read_text())
    if current.get('selected_module', {}).get('ASR') != 'XunfeiStreamASR':
        raise ValueError('当前ASR已被其他操作改变，未覆盖配置')
    if 'ASR' in before.get('selected_module', {}):
        current['selected_module']['ASR'] = before['selected_module']['ASR']
    else:
        current['selected_module'].pop('ASR', None)
    if 'XunfeiStreamASR' in before.get('ASR', {}):
        current['ASR']['XunfeiStreamASR'] = before['ASR']['XunfeiStreamASR']
    else:
        current['ASR'].pop('XunfeiStreamASR', None)
    temp = PRIVATE/'config-rollback.yaml'
    with temp.open('w') as f: y.dump(current, f)
    temp.chmod(0o600); os.replace(temp, CONFIG); STATE.unlink()
    print('已恢复之前的ASR配置；需要重启语音桥生效')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check','probe','apply','rollback'])
    parser.add_argument('--credentials', type=Path, default=PRIVATE/'credentials.yaml')
    parser.add_argument('--audio', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'rollback': rollback(); return
        settings = candidate(args.credentials)
        if args.action == 'check': print('密钥字段已填写，待真实云端验证；当前ASR未改变'); return
        if not args.audio: raise ValueError('请通过 --audio 提供测试 WAV 文件')
        text = asyncio.run(probe(settings, args.audio))
        print('讯飞最终识别结果:', text)
        if args.action == 'apply': apply(settings)
    except Exception as error:
        # Never print transport exceptions or signed WebSocket URLs containing credentials.
        print(str(error) if isinstance(error, (ValueError, FileNotFoundError)) else f'验证失败：{type(error).__name__}；未确认切换', file=sys.stderr)
        raise SystemExit(1)

if __name__ == '__main__': main()
