import unittest,json
from reaction_continuity import audio_space,own_space,decision_context,parse_understanding,parse_decision

class ContinuityTests(unittest.TestCase):
    def test_present_audio_never_exposes_future_transcript_or_end(self):
        h={'cues':[{'id':'a','start':5,'end':15,'available_at':20,'text':'future words'}]}
        x=audio_space(h,8)
        self.assertTrue(x['speaking_now']);self.assertEqual(x['recent_heard'],[])
        self.assertNotIn('15',json.dumps(x));self.assertNotIn('future words',json.dumps(x))
        self.assertEqual(audio_space(h,20)['recent_heard'][0]['text'],'future words')
    def test_own_occupancy_and_recent_words_are_explicit_estimates(self):
        x=own_space([{'action':'speak','wall':10,'estimated_seconds':8,'text':'刚才的话'}],15)
        self.assertEqual(x['currently_speaking'][0]['remaining'],3)
        self.assertEqual(x['recent'][0]['text'],'刚才的话')
    def test_private_uncertainties_not_promoted_to_public_context(self):
        x=decision_context({'story':'一人经历身份变化','cast':[],'private_checks':['voice unverified'],'hypotheses':[]},{}, {},'',10)
        self.assertNotIn('voice unverified',json.dumps(x));self.assertIn('source_audio',x)
    def test_working_narrative_does_not_require_voice_identity(self):
        x={'story':'这可能是同一人的视角','cast':[],'hypotheses':[{'claim':'同一人','status':'working','evidence_at':[10]}],'private_checks':['声音未知'],'event':{'consider':False}}
        self.assertEqual(parse_understanding(json.dumps(x),10)['hypotheses'][0]['status'],'working')
        x['hypotheses'][0]['evidence_at']=[11]
        with self.assertRaises(ValueError):parse_understanding(json.dumps(x),10)
    def test_choice_is_not_gated_by_frequency_or_length(self):
        for a in ('continue','speak','pause'):
            x={'action':a,'text':'' if a=='continue' else '长话'*100,'attention':'','reason':'','listening_tradeoff':''}
            self.assertEqual(parse_decision(json.dumps(x))['action'],a)
    def test_withholding_speech_cannot_be_mistaken_for_pausing_video(self):
        x={'action':'watch_silently','text':'','attention':'','reason':'先听对白','listening_tradeoff':''}
        self.assertEqual(parse_decision(json.dumps(x))['action'],'continue')
        x['action']='pause_video_and_speak'
        with self.assertRaises(ValueError):parse_decision(json.dumps(x))
        x['text']='想暂停说的话'
        self.assertEqual(parse_decision(json.dumps(x))['action'],'pause')

if __name__=='__main__':unittest.main()
