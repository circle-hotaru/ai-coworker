from unittest.mock import patch
import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from core.utils.push_store import PushStore, DEVICE_AGENTS
REVIEWER='02:00:00:00:00:01'
RESEARCHER='02:00:00:00:00:02'
OPERATOR='02:00:00:00:00:03'
class Tests(unittest.TestCase):
 def setUp(self):
  registry=patch.dict(DEVICE_AGENTS,{REVIEWER:'reviewer',RESEARCHER:'researcher',OPERATOR:'operator'},clear=True)
  registry.start();self.addCleanup(registry.stop)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=PushStore(Path(self.tmp.name)/'state.sqlite');self.session=self.store.enroll('Voice-Task-1',REVIEWER)
 def test_primary_before_completion(self):
  self.store.enqueue(self.session,'r1','first answer');self.assertIsNone(self.store.next())
  self.store.complete_primary(self.session,'r1','first answer');self.assertIsNone(self.store.next())
 def test_followup_durable_dedup(self):
  self.store.complete_primary(self.session,'r1','first answer')
  token=self.store.enqueue(self.session,'r2','later answer')
  self.assertEqual(token,self.store.enqueue(self.session,'r2','later answer'))
  self.assertEqual(PushStore(self.store.path).next(),(token,'later answer','pending'))
  self.store.set_state(token,'accepted');self.assertEqual(self.store.next()[2],'accepted')
  self.store.set_state(token,'done');self.assertIsNone(self.store.next())
 def test_distinct_updates_in_one_later_run(self):
  self.store.complete_primary(self.session,'primary','first')
  one=self.store.enqueue(self.session,'later','progress update')
  two=self.store.enqueue(self.session,'later','final result')
  self.assertNotEqual(one,two)
  self.assertEqual(self.store.next()[0],one)
  self.store.set_state(one,'done');self.assertEqual(self.store.next()[0],two)
 def test_operator_isolated_and_not_blocked_by_reviewer(self):
  operator=self.store.enroll('Operator-task',OPERATOR)
  self.store.complete_primary(operator,'w-primary','first operator answer')
  token=self.store.enqueue(operator,'w-followup','later operator answer')
  self.assertEqual(self.store.owner(token),OPERATOR)
  self.assertEqual(self.store.next(OPERATOR)[0],token)
  self.assertIsNone(self.store.next(REVIEWER))
  reviewer=self.store.enqueue(self.session,'b-followup','later reviewer answer')
  self.assertEqual(self.store.owner(reviewer),REVIEWER)
  self.assertIsNone(self.store.next(REVIEWER))
  self.store.complete_primary(self.session,'b-primary','first reviewer answer')
  self.assertEqual(self.store.next(REVIEWER)[0],reviewer)
  self.assertEqual(self.store.next(OPERATOR)[0],token)
 def test_existing_operator_session_can_receive_future_events(self):
  self.store.allow_existing('existing-operator',OPERATOR)
  session='agent:operator:openai-user:existing-operator'
  token=self.store.enqueue(session,'future','new update')
  self.assertEqual(self.store.next(OPERATOR)[0],token)
 def test_researcher_queue_is_independent_and_owns_its_audio(self):
  session=self.store.enroll('Researcher-task',RESEARCHER)
  self.store.complete_primary(session,'m-primary','first researcher answer')
  token=self.store.enqueue(session,'m-followup','later researcher answer')
  self.assertEqual(self.store.owner(token),RESEARCHER)
  self.assertEqual(self.store.next(RESEARCHER)[0],token)
  self.assertIsNone(self.store.next(REVIEWER))
  self.assertIsNone(self.store.next(OPERATOR))
 def test_existing_researcher_session_can_receive_future_events(self):
  self.store.allow_existing('existing-researcher',RESEARCHER)
  token=self.store.enqueue('agent:researcher:openai-user:existing-researcher','future','new update')
  self.assertEqual(self.store.next(RESEARCHER)[0],token)
  self.assertIsNone(self.store.enqueue('agent:researcher:main','future','private chat'))
 def test_unrelated_session_rejected(self):
  self.assertIsNone(self.store.enqueue('agent:reviewer:main','r','private chat'))
 def test_late_primary_after_next_turn(self):
  self.store.complete_primary(self.session,'r1','first answer');self.store.enroll('Voice-Task-1',REVIEWER)
  self.store.complete_primary(self.session,'r2','second answer');self.store.enqueue(self.session,'r1','first answer')
  self.assertIsNone(self.store.next())
 def test_restart_recovers_gate_and_private_db(self):
  token=self.store.enqueue(self.session,'late','finished after disconnect');self.assertIsNone(self.store.next())
  self.store.recover();self.assertEqual(self.store.next()[0],token)
  self.assertEqual(os.stat(self.store.path).st_mode & 0o777,0o600)
if __name__=='__main__':unittest.main()
