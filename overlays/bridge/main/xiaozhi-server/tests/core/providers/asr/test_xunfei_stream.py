"""Protocol regression tests; all credentials and WebSockets here are fake."""
import asyncio
import base64
import hashlib
import hmac
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from core.providers.asr.xunfei_stream import ASRProvider
from core.providers.asr.base import ASRProviderBase

CONFIG = dict(app_id='test-app', api_key='test-key', api_secret='test-secret',
              domain='spark_asr_v2', ltc=1, dwa='wpgs', eos=60000,
              context={'bias': {'hotword': [{'text': 'Reviewer', 'weight': 0.8}]}})

class Socket:
    def __init__(self, responses=()):
        self.sent = []
        self.responses = list(responses)
    async def send(self, value): self.sent.append(json.loads(value))
    async def recv(self): return json.dumps(self.responses.pop(0))
    async def close(self): pass

def packet(sn, words, status=1, **extra):
    text = dict(sn=sn, ws=[{'cw': [{'w': words}, {'w': 'NOT_A_SECOND_WORD'}]}])
    text.update(extra)
    return {'header': {'code': 0, 'status': status}, 'payload': {'result': {
        'status': status, 'text': base64.b64encode(json.dumps(text).encode()).decode()}}}

class Tests(unittest.IsolatedAsyncioTestCase):
    def test_wss_signature_and_v2_context(self):
        p = ASRProvider(CONFIG, True)
        url = urlparse(p.create_url()); q = parse_qs(url.query)
        self.assertEqual(url.scheme, 'wss')
        self.assertEqual(url.hostname, 'iat.cn-huabei-1.xf-yun.com')
        signature = base64.b64encode(hmac.new(b'test-secret',
            f"host: {url.hostname}\ndate: {q['date'][0]}\nGET /v1 HTTP/1.1".encode(), hashlib.sha256).digest()).decode()
        self.assertIn(f'signature="{signature}"', base64.b64decode(q['authorization'][0]).decode())
        self.assertEqual(p.iat_params['result']['format'], 'json')
        self.assertEqual(json.loads(p.iat_params['context'])['bias']['hotword'][0]['text'], 'Reviewer')
        with self.assertRaises(ValueError): ASRProvider({**CONFIG, 'api_key': ''}, True)

    def test_dynamic_replacement_preserves_latin_names(self):
        p = ASRProvider(CONFIG, True)
        p._merge_result({'sn': 1, 'ws': [{'cw': [{'w': '联系邓'}, {'w': 'wrong'}]}]})
        p._merge_result({'sn': 2, 'ws': [{'cw': [{'w': '联系 Reviewer'}]}]}, {'pgs': 'rpl', 'rg': [1, 1]})
        self.assertEqual(p.text, '联系 Reviewer')

    async def test_cached_audio_once_in_original_order(self):
        p = ASRProvider(CONFIG, True); ws = Socket()
        conn = SimpleNamespace(client_listen_mode='manual', asr_audio=[b'pre'], client_voice_stop=False)
        p._forward_results = AsyncMock()
        with patch('core.providers.asr.xunfei_stream.websockets.connect', AsyncMock(return_value=ws)):
            await p.receive_audio(conn, b'current', True)
        await p.forward_task
        self.assertEqual([base64.b64decode(f['payload']['audio']['audio']) for f in ws.sent], [b'pre', b'current'])
        self.assertEqual([f['header']['status'] for f in ws.sent], [0, 1])
        self.assertEqual(ws.sent[0]['payload']['audio']['bit_depth'], 16)
        self.assertNotIn('parameter', ws.sent[1])

    async def test_stop_sent_once_without_premature_submission(self):
        p = ASRProvider(CONFIG, True); p.asr_ws = Socket(); p.is_processing = p.server_ready = True
        with patch.object(ASRProviderBase, 'handle_voice_stop', new_callable=AsyncMock) as submit:
            await p.handle_voice_stop(None, [])
            await p._send_stop_request()
            submit.assert_not_awaited()
        self.assertEqual([f['header']['status'] for f in p.asr_ws.sent], [2])
        self.assertEqual(p.asr_ws.sent[0]['payload']['audio']['status'], 2)

    async def test_stop_waits_for_handshake_and_cached_audio(self):
        p = ASRProvider(CONFIG, True); p.asr_ws = Socket(); p.is_processing = True
        task = asyncio.create_task(p._send_stop_request())
        await asyncio.sleep(0.01)
        self.assertEqual(p.asr_ws.sent, [])
        p.server_ready = True
        await task
        self.assertEqual([f['header']['status'] for f in p.asr_ws.sent], [2])

    async def test_final_result_submitted_once_after_correction(self):
        p = ASRProvider(CONFIG, True); ws = Socket([packet(1, '联系邓'), packet(2, '联系 Reviewer', 2, pgs='rpl', rg=[1,1])]); p.asr_ws = ws
        conn = SimpleNamespace(stop_event=threading.Event(), asr_audio=[b'audio'], reset_audio_states=lambda:None)
        result = []
        async def submit(*args): result.append(p.text)
        with patch.object(ASRProviderBase, 'handle_voice_stop', side_effect=submit) as done:
            await p._forward_results(conn)
            self.assertEqual(done.await_count, 1)
        self.assertEqual(result, ['联系 Reviewer']); self.assertEqual(ws.sent, [])

    async def test_cloud_error_never_submits_partial_text(self):
        p = ASRProvider(CONFIG, True); p.asr_ws = Socket([{'header': {'code': 11200, 'status': 2}}]); p.text = 'partial'
        conn = SimpleNamespace(stop_event=threading.Event(), reset_audio_states=lambda:None)
        with patch.object(ASRProviderBase, 'handle_voice_stop', new_callable=AsyncMock) as submit:
            await p._forward_results(conn)
            submit.assert_not_awaited()

if __name__ == '__main__': unittest.main()
