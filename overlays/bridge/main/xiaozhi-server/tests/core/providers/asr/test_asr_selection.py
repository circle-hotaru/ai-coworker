import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from core.utils.asr_selection import resolve_asr


class Tests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "selected_module": {"ASR": "XunfeiStreamASR"},
            "ASR": {
                "XunfeiStreamASR": dict(type="xunfei_stream", app_id="test-app",
                                        api_key="test-key", api_secret="test-secret"),
                "FunASR": dict(type="fun_local", model_dir="models/SenseVoiceSmall",
                               language="zh", output_dir="tmp/"),
            },
        }

    def test_complete_credentials_use_xunfei(self):
        name, kind, settings, missing = resolve_asr(self.config)
        self.assertEqual((name, kind, missing), ("XunfeiStreamASR", "xunfei_stream", ()))
        self.assertIs(settings, self.config["ASR"][name])

    def test_any_missing_credential_uses_existing_local_settings(self):
        for key in ("app_id", "api_key", "api_secret"):
            for value in (None, "", "  ", "你的密钥", 123):
                with self.subTest(key=key, value=value):
                    config = copy.deepcopy(self.config)
                    config["ASR"]["XunfeiStreamASR"][key] = value
                    before = copy.deepcopy(config)
                    name, kind, settings, missing = resolve_asr(config)
                    self.assertEqual((name, kind, missing), ("FunASR", "fun_local", (key,)))
                    self.assertIs(settings, config["ASR"]["FunASR"])
                    self.assertEqual(config, before)
        for key in ("app_id", "api_key", "api_secret"):
            del self.config["ASR"]["XunfeiStreamASR"][key]
        self.assertEqual(len(resolve_asr(self.config)[3]), 3)

    def test_other_explicit_provider_unchanged(self):
        self.config["selected_module"]["ASR"] = "FunASR"
        self.assertEqual(resolve_asr(self.config)[:2], ("FunASR", "fun_local"))

    def test_missing_local_fallback_fails_clearly(self):
        self.config["ASR"]["XunfeiStreamASR"]["api_key"] = ""
        del self.config["ASR"]["FunASR"]
        with self.assertRaisesRegex(ValueError, "本地 FunASR"):
            resolve_asr(self.config)

    def test_factory_receives_local_settings_and_delete_flag(self):
        from core.utils.modules_initialize import initialize_asr
        self.config["ASR"]["XunfeiStreamASR"]["app_id"] = ""
        self.config["delete_audio"] = "false"
        with patch("core.utils.modules_initialize.asr.create_instance") as factory:
            self.assertIs(initialize_asr(self.config), factory.return_value)
        factory.assert_called_once_with("fun_local", self.config["ASR"]["FunASR"], False)


if __name__ == "__main__":
    unittest.main()
