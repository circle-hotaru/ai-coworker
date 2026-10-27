import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from aiohttp import web
from core.api.push_handler import PushService
from core.utils.push_store import PushStore, DEVICE_AGENTS

REVIEWER='02:00:00:00:00:01'
RESEARCHER='02:00:00:00:00:02'
OPERATOR='02:00:00:00:00:03'
class Tests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  registry=patch.dict(DEVICE_AGENTS,{REVIEWER:'reviewer',RESEARCHER:'researcher',OPERATOR:'operator'},clear=True)
  registry.start();self.addCleanup(registry.stop)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.service=PushService.__new__(PushService)
  self.service.store=PushStore(Path(self.tmp.name)/'push.sqlite')
  self.service.media=Path(self.tmp.name)
  self.session=self.service.store.enroll('operator-test',OPERATOR)
  self.service.store.complete_primary(self.session,'primary','first')
 def request(self,remote,payload):
  return SimpleNamespace(remote=remote,content_length=200,json=AsyncMock(return_value=payload))
 async def test_operator_event_only_accepts_enrolled_loopback(self):
  payload={'session':self.session,'run':'later','text':'new reply'}
  response=await self.service.events(self.request('127.0.0.1',payload))
  self.assertEqual(response.status,200)
  with self.assertRaises(web.HTTPForbidden):
   await self.service.events(self.request('192.168.50.9',payload))
  with self.assertRaises(web.HTTPForbidden):
   await self.service.events(self.request('127.0.0.1',{**payload,'session':'agent:operator:main'}))
 async def test_audio_cannot_cross_devices(self):
  token=self.service.store.enqueue(self.session,'later','reply')
  (self.service.media/(token+'.ogg')).write_bytes(b'fake test audio')
  with patch.dict('core.api.push_handler._peers',{OPERATOR:'192.168.50.121',REVIEWER:'192.168.50.155'},clear=True):
   request=SimpleNamespace(remote='192.168.50.121',match_info={'token':token})
   self.assertEqual((await self.service.audio(request)).status,200)
   request.remote='192.168.50.155'
   with self.assertRaises(web.HTTPForbidden):await self.service.audio(request)
 async def test_researcher_event_and_audio_isolation(self):
  session=self.service.store.enroll('researcher-test',RESEARCHER)
  self.service.store.complete_primary(session,'primary','first')
  response=await self.service.events(self.request('127.0.0.1',{'session':session,'run':'later','text':'researcher update'}))
  self.assertEqual(response.status,200)
  token=self.service.store.next(RESEARCHER)[0]
  (self.service.media/(token+'.ogg')).write_bytes(b'fake test audio')
  with patch.dict('core.api.push_handler._peers',{OPERATOR:'192.168.50.121',REVIEWER:'192.168.50.155',RESEARCHER:'192.168.50.156'},clear=True):
   request=SimpleNamespace(remote='192.168.50.156',match_info={'token':token})
   self.assertEqual((await self.service.audio(request)).status,200)
   for address in ['192.168.50.121','192.168.50.155']:
    request.remote=address
    with self.assertRaises(web.HTTPForbidden):await self.service.audio(request)
if __name__=='__main__':unittest.main()
