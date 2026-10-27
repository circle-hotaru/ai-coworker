import asyncio,unittest,sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from core.api import dance_handler as m
class Tests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  m._peer=None;m._seen=0
  p=patch.object(m.registry,'DANCE_DEVICE','02:00:00:00:00:03');p.start();self.addCleanup(p.stop)
  p=patch.dict(m.registry.DEVICE_LABELS,{'02:00:00:00:00:03':'Operator'},clear=True);p.start();self.addCleanup(p.stop)
 async def test_loopback_only_and_offline(self):
  self.assertEqual((await m.handle_dance(SimpleNamespace(remote='192.168.50.1',match_info={'action':'start'}))).status,403)
  self.assertEqual((await m.handle_dance(SimpleNamespace(remote='127.0.0.1',match_info={'action':'start'}))).status,503)
 async def test_registration_only_operator_private_ip(self):
  m.record_operator_peer('02:00:00:00:00:01','192.168.50.10');self.assertIsNone(m._peer)
  m.record_operator_peer(m.registry.DANCE_DEVICE,'127.0.0.1');self.assertIsNone(m._peer)
  m.record_operator_peer(m.registry.DANCE_DEVICE,'192.168.50.138');self.assertEqual(m._peer,'192.168.50.138')
 async def test_forward_stop_and_surface_firmware_failure(self):
  m.record_operator_peer(m.registry.DANCE_DEVICE,'192.168.50.138');calls=[]
  class Reply:
   status=409
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def json(self):return {'device':'Operator','state':'fault'}
  class Client:
   def __init__(self,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def post(self,url,**kw):calls.append(url);return Reply()
  with patch.object(m,'ClientSession',Client):
   response=await m.handle_dance(SimpleNamespace(remote='127.0.0.1',match_info={'action':'stop'}))
  self.assertEqual(response.status,409);self.assertEqual(calls,['http://192.168.50.138:8020/dance/stop'])
if __name__=='__main__':unittest.main()
