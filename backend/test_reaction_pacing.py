import array
import json
import tempfile
import unittest
import wave
from pathlib import Path

import imageio_ffmpeg
from reaction_intent import parse_intent
from reaction_pacing import PlaybackTimeline, source_audio, pause_duration, parse_review
from reaction_tools import execute_playback_tool
from reaction_produce import exclusive_job, execute_production_tool


class PacingTests(unittest.TestCase):
    def test_separate_explicit_tool_envelope_is_not_silently_lost(self):
        raw='{"choice":"keep","reason":"随口反应"}{"name":"reaction_continue","arguments":{}}'
        self.assertEqual(parse_review(raw)['tool_call']['name'],'reaction_continue')
        with self.assertRaises(ValueError):
            parse_review('{"choice":"keep","reason":"随口反应","tool_call":{"name":"reaction_pause","arguments":{"reason":"x","resume":"speech_end"}}}')

    def test_tool_retry_is_idempotent_and_replay_is_bounded(self):
        state={'input':{'seconds':30},'pauses':[]}
        call={'name':'reaction_pause','arguments':{'reason':'讨论选择','resume':'speech_end'}}
        first=execute_playback_tool(state,call,call_id='s1',cursor=4,speech_duration=2)
        restored=json.loads(json.dumps(state))
        self.assertEqual(execute_playback_tool(restored,call,call_id='s1',cursor=4,speech_duration=2),first)
        self.assertEqual(len(restored['pauses']),1)
        self.assertEqual(first['resume_at_source'],4)
        self.assertEqual(first['output_resume'],6)
        result=execute_playback_tool(state,{'name':'reaction_replay','arguments':{'seconds':8}},call_id='r1',cursor=4)
        self.assertEqual((result['from'],result['through']),(0,4))
        with self.assertRaises(ValueError):
            execute_playback_tool(state,{'name':'exec','arguments':{}},call_id='x',cursor=4)

    def test_production_ownership_and_status_do_not_launch_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock'
            with exclusive_job(path):
                with self.assertRaises(RuntimeError):
                    with exclusive_job(path):pass
            with exclusive_job(path):pass
            self.assertEqual(execute_production_tool({'output':folder},{'name':'reaction_production_status'}),{'phase':'not_started'})
            with self.assertRaises(ValueError):
                execute_production_tool({'output':folder},{'name':'reaction_produce','arguments':{'video':'other.mp4'}})

    def test_clock_holds_only_source_and_resumes_without_skipping(self):
        t=PlaybackTimeline([{'source':2,'duration':3},{'source':6,'duration':2}])
        self.assertEqual([t.source_at(x) for x in (1,2,3,4.9,5,8,9,10,11,12)],
                         [1,2,2,2,2,5,6,6,6,7])
        self.assertEqual(t.output_at(6,after=False),9)
        self.assertEqual(t.output_at(6),11)
        self.assertEqual(t.output_at(10),15)
        self.assertEqual(PlaybackTimeline().source_at(42),42)

    def test_hold_length_covers_entire_audio_frame(self):
        self.assertGreaterEqual(pause_duration(4.012),4.012)
        self.assertAlmostEqual(pause_duration(4.012)*24,97)

    def test_model_must_explain_pause_not_duration_rule(self):
        with self.assertRaises(ValueError):
            parse_intent('{"action":"speak","delivery":"pause"}',0,10)
        p=parse_intent('{"action":"speak","delivery":"pause","pause_reason":"想讨论角色的选择"}',0,10)
        self.assertEqual(p['delivery'],'pause')
        self.assertEqual(parse_review('{"choice":"keep","reason":"想一口气说完"}')['choice'],'keep')
        with self.assertRaises(ValueError):
            parse_review('{"choice":"shorten","reason":"收掉铺垫","text":""}')

    def test_checkpoint_timeline_roundtrip_and_duplicate_rejection(self):
        pauses=[{'source':4,'duration':2,'reason':'自主选择'}]
        self.assertEqual(PlaybackTimeline(json.loads(json.dumps(pauses))).source_at(5),4)
        with self.assertRaises(ValueError):PlaybackTimeline(pauses+pauses)

    def test_original_pcm_is_unattenuated_and_sample_exact_after_hold(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); src=p/'source.wav'; rate=48000
            samples=array.array('h',[1000]*rate+[-2000]*rate)
            with wave.open(str(src),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(samples.tobytes())
            ff=imageio_ffmpeg.get_ffmpeg_exe()
            clean=source_audio(ff,src,p/'clean.pcm',0,2,[]).read_bytes()
            held=source_audio(ff,src,p/'held.pcm',0,2,[{'source':1,'duration':.5}]).read_bytes()
            boundary=rate*8; silence=rate*4
            self.assertEqual(held[:boundary],clean[:boundary])
            self.assertEqual(held[boundary:boundary+silence],bytes(silence))
            self.assertEqual(held[boundary+silence:],clean[boundary:])


if __name__=='__main__':unittest.main()
