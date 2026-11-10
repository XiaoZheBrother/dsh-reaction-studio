import unittest
from reaction_experience import apply_updates,snapshot,expression_context,playback_constraints

class ExperienceTests(unittest.TestCase):
    def record(self,**kw):return dict(id='person-a',kind='entity',claim='unknown person',status='tentative',confidence=.4,evidence_at=[2],**kw)
    def test_revision_preserves_original_and_history(self):
        first=apply_updates(None,[self.record()],2)
        update={**self.record(),'claim':'identified person','status':'revised','evidence_at':[5],'confidence':.8}
        second=apply_updates(first,[update],5)
        self.assertEqual(first['records']['person-a']['claim'],'unknown person')
        self.assertEqual(second['records']['person-a']['revision'],2)
        self.assertEqual(second['history'][1]['before'],first['records']['person-a'])
    def test_future_evidence_and_identity_type_changes_rejected(self):
        with self.assertRaises(ValueError):apply_updates(None,[self.record()],1)
        first=apply_updates(None,[self.record()],2)
        with self.assertRaises(ValueError):apply_updates(first,[{**self.record(),'kind':'relation'}],3)
    def test_expression_projection_does_not_expose_raw_audit(self):
        state={'actor_attention':'my question','events':[{'raw_intent':'private audit'}]}
        result=expression_context(state,{'cursor':3,'story':'current event','topic':'my thought','raw_intent':'private audit'},[])
        self.assertNotIn('private audit',str(result))
        self.assertEqual(result['your_attention'],'my question')
    def test_short_and_long_speech_are_equal_without_technical_conflict(self):
        for duration in [.3,30]:self.assertFalse(any(playback_constraints(10,duration,8,100).values()))
        self.assertEqual(playback_constraints(10,5,12,14),{'overlap_seconds':2,'beyond_source_seconds':1})
    def test_pause_does_not_consume_remaining_source(self):
        self.assertFalse(any(playback_constraints(95,30,90,100,'pause').values()))

if __name__=='__main__':unittest.main()
