import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.utils.voice_turn_policy import (accept_command, begin_capture, capture_allowed,
    empty_capture_expired, finish_reply)

class VoiceTurnTests(unittest.TestCase):
    def conn(self, mode='continuous'):
        return SimpleNamespace(llm=SimpleNamespace(route={'activation_mode':'button_only',
            'interaction_mode':mode}), config={'wakeup_words':['你好小智']},
            close_after_chat=False, client_have_voice=False)

    def test_two_turns_and_playback_gate(self):
        c = self.conn()
        self.assertFalse(accept_command(c, '旁谈'))
        begin_capture(c)
        self.assertFalse(accept_command(c, '你好小智'))
        self.assertTrue(accept_command(c, '第一轮'))
        self.assertFalse(c.close_after_chat)
        self.assertFalse(accept_command(c, '播放时旁谈'))
        finish_reply(c)
        self.assertFalse(capture_allowed(c))
        begin_capture(c)
        self.assertTrue(accept_command(c, '第二轮'))

    def test_empty_capture_five_seconds(self):
        c = self.conn()
        with patch('core.utils.voice_turn_policy.time.monotonic', return_value=100):
            begin_capture(c)
        with patch('core.utils.voice_turn_policy.time.monotonic', return_value=104.99):
            self.assertFalse(empty_capture_expired(c, False))
        with patch('core.utils.voice_turn_policy.time.monotonic', return_value=105):
            self.assertTrue(empty_capture_expired(c, False))

    def test_speech_then_silence_submits_instead_of_closing(self):
        c = self.conn()
        begin_capture(c)
        self.assertFalse(empty_capture_expired(c, True))
        c.client_have_voice = True
        self.assertFalse(empty_capture_expired(c, False))
        self.assertTrue(accept_command(c, '完整指令'))
        self.assertFalse(empty_capture_expired(c, False))

    def test_reply_time_does_not_count_towards_silence(self):
        c = self.conn()
        begin_capture(c)
        accept_command(c, '问题')
        with patch('core.utils.voice_turn_policy.time.monotonic', return_value=10000):
            self.assertFalse(empty_capture_expired(c, False))
            finish_reply(c)
            self.assertFalse(empty_capture_expired(c, False))
            begin_capture(c)
            self.assertFalse(empty_capture_expired(c, False))

    def test_single_turn_unchanged(self):
        c = self.conn('single_turn')
        begin_capture(c)
        self.assertTrue(accept_command(c, '问题'))
        self.assertTrue(c.close_after_chat)
        finish_reply(c)
        self.assertFalse(capture_allowed(c))

if __name__ == '__main__': unittest.main()
