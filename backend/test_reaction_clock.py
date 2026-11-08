import unittest,json,subprocess
from pathlib import Path
from reaction_clock import can_voice

class SpeechSlotTests(unittest.TestCase):
    def test_autonomous_silence_never_acquires_voice(self):
        self.assertFalse(can_voice({'action':'continue'}, {'busy':False}))
    def test_new_thought_during_speech_is_deferred(self):
        self.assertFalse(can_voice({'action':'speak'}, {'busy':True}))
        self.assertFalse(can_voice({'action':'speak'}, {'busy':False,'pending':[{'text':'already waiting'}]}))
    def test_fresh_choice_can_speak_as_soon_as_voice_is_free(self):
        self.assertTrue(can_voice({'action':'speak'}, {'busy':False,'pending':[]}))
        self.assertTrue(can_voice({'action':'speak'}, {'busy':False,'pendingThought':{'topic':'old thought'}}))

class CaptionRenderingTests(unittest.TestCase):
    def test_spoken_caption_wrap_does_not_stop_animation(self):
        html=Path(__file__).with_name('reaction_clock.html').read_text(encoding='utf-8')
        wrap=html.split('function wrap',1)[1].split('function caption',1)[0]
        code='function wrap'+wrap+'console.log(JSON.stringify(wrap("1234567890ab",10)))'
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),['1234567890','ab'])

if __name__=='__main__':unittest.main()
