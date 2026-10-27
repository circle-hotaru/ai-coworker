import sys
import tempfile
import unittest
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from core.providers.llm.openclaw_local.openclaw_local import LLMProvider

class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"partial"},"index":0}]}\n\n'
        raise httpx.ReadTimeout('simulated stream timeout')

class Tests(unittest.TestCase):
    def provider(self, transport):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        (Path(self.tmp.name)/'devices.yaml').write_text('devices: {}\n')
        p = LLMProvider(dict(base_url='http://localhost:1/v1', api_key='fake',
            device_map=str(Path(self.tmp.name)/'devices.yaml')))
        p.route = {'conversation_id':'test'}
        p.client = p.client.with_options(http_client=httpx.Client(transport=transport))
        self.addCleanup(p.client.close)
        self.assertEqual(p.client.max_retries, 0)
        self.assertEqual(p.client.timeout.read, 1800)
        return p

    def test_request_timeout_never_retries_and_warns_of_unknown_state(self):
        calls = []
        def respond(request):
            calls.append(request)
            raise httpx.ReadTimeout('simulated')
        p = self.provider(httpx.MockTransport(respond))
        text = ''.join(p.response('s', [{'role':'user','content':'task'}]))
        self.assertEqual(len(calls), 1)
        self.assertIn('可能仍在后台处理', text)
        self.assertIn('请勿重复提交', text)

    def test_stream_timeout_preserves_partial_and_warns(self):
        p = self.provider(httpx.MockTransport(lambda request: httpx.Response(200,
            headers={'content-type':'text/event-stream'}, stream=BrokenStream())))
        text = ''.join(p.response('s', [{'role':'user','content':'task'}]))
        self.assertTrue(text.startswith('partial'))
        self.assertIn('请勿重复提交', text)

if __name__ == '__main__': unittest.main()
