import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch
import yaml
spec=importlib.util.spec_from_file_location('xunfei_manage', Path(__file__).with_name('manage.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
    def test_fresh_async_probe_reaches_mock_transport(self):
        code = '''
import asyncio, importlib.util, sys, tempfile, wave
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('manage',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as folder:
    audio=Path(folder)/'test.wav'
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\\0'*1280)
    with patch('websockets.connect',side_effect=RuntimeError('mock_transport_reached')):
        try:asyncio.run(m.probe(dict(app_id='fake',api_key='fake',api_secret='fake'),audio))
        except RuntimeError as error:assert str(error)=='mock_transport_reached',type(error).__name__
        else:raise AssertionError('Mock transport not reached')
'''
        result=subprocess.run([sys.executable,'-c',code,str(Path(m.__file__).resolve())],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_missing_credentials_do_not_change_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'keys.yaml';p.write_text('app_id: ""\napi_key: ""\napi_secret: ""\n')
            with self.assertRaises(ValueError):m.candidate(p)
    def test_apply_and_rollback_preserve_other_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'config.yaml';private=root/'private';state=private/'state.json'
            config.write_text(yaml.safe_dump({'selected_module':{'ASR':'FunASR','LLM':'OpenClawLocal'},'ASR':{'FunASR':{'language':'zh'}},'other':1}))
            with patch.multiple(m,CONFIG=config,PRIVATE=private,STATE=state):
                m.apply({'type':'xunfei_stream','app_id':'fake','api_key':'fake','api_secret':'fake'})
                updated=yaml.safe_load(config.read_text());self.assertEqual(updated['selected_module']['ASR'],'XunfeiStreamASR');self.assertEqual(updated['selected_module']['LLM'],'OpenClawLocal')
                updated['other']=2;config.write_text(yaml.safe_dump(updated))
                with self.assertRaises(ValueError):m.apply({})
                m.rollback()
                restored=yaml.safe_load(config.read_text());self.assertEqual(restored['selected_module']['ASR'],'FunASR');self.assertEqual(restored['other'],2);self.assertNotIn('XunfeiStreamASR',restored['ASR'])
    def test_candidate_v2_context(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'keys.yaml';p.write_text('app_id: "a"\napi_key: "b"\napi_secret: "c"\n')
            c=m.candidate(p);self.assertEqual(c['domain'],'spark_asr_v2');self.assertEqual(c['ltc'],1);self.assertEqual(c['api_key'],'b')
if __name__=='__main__':unittest.main()
