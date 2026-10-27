import copy,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from core.utils.device_tts import device_tts_config

class DeviceVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.mapping=Path(self.temp.name)/'devices.yaml'
        self.mapping.write_text('devices:\n  reviewer-mac:\n    tts_voice: zh-CN-YunxiNeural\n  operator-mac: {}\n')
        self.config={'selected_module':{'TTS':'EdgeTTS','LLM':'Local'},
                     'LLM':{'Local':{'device_map':str(self.mapping)}},
                     'TTS':{'EdgeTTS':{'type':'edge','voice':'zh-CN-XiaoxiaoNeural','private_voice':'old','rate':'0'}}}
    def test_live_route_override_does_not_change_shared_default(self):
        before=copy.deepcopy(self.config)
        result=device_tts_config(self.config,route={'tts_voice':'zh-CN-YunxiNeural'})
        self.assertEqual(result['TTS']['EdgeTTS']['voice'],'zh-CN-YunxiNeural')
        self.assertEqual(result['TTS']['EdgeTTS']['private_voice'],'zh-CN-YunxiNeural')
        self.assertEqual(self.config,before)
    def test_push_device_lookup_keeps_other_devices_default(self):
        male=device_tts_config(self.config,device_id='REVIEWER-MAC')
        other=device_tts_config(self.config,device_id='operator-mac')
        self.assertEqual(male['TTS']['EdgeTTS']['voice'],'zh-CN-YunxiNeural')
        self.assertIs(other,self.config)
        self.assertEqual(other['TTS']['EdgeTTS']['private_voice'],'old')
    def test_no_override_keeps_original_config(self):
        self.assertIs(device_tts_config(self.config,route={}),self.config)
        self.assertIs(device_tts_config(self.config,device_id='unknown'),self.config)
    def test_unsupported_provider_rejects_edge_voice_override(self):
        self.config['TTS']['EdgeTTS']['type']='other'
        with self.assertRaises(ValueError):
            device_tts_config(self.config,route={'tts_voice':'zh-CN-YunxiNeural'})
if __name__=='__main__':unittest.main()
