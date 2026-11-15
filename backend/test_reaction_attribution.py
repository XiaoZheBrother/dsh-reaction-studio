import json,unittest
from reaction_attribution import update_utterances,parse_check,recent_utterances,enforce_bindings

class AttributionTests(unittest.TestCase):
    def row(self):
        return {'id':'u1','text':'我很累','at':8,'source':'subtitle','cue_id':None,'mode':'unknown','mode_status':'unknown','speaker':'p1','speaker_status':'confirmed','evidence':['visual_presence','visible_mouth_movement'],'reason':'人物在画面里'}
    def test_visible_person_cannot_be_confirmed_speaker(self):
        s=update_utterances({},[self.row()],10,[])
        self.assertEqual(s['u1']['speaker_status'],'working')
        self.assertEqual(s['u1']['mode'],'unknown')
    def test_narrative_subject_and_spoken_delivery_are_independent(self):
        row={**self.row(),'mode':'inner','mode_status':'working','speaker_status':'working','evidence':['discourse_continuity']}
        s=update_utterances({},[row],10,[])
        self.assertEqual(s['u1']['speaker'],'p1');self.assertEqual(s['u1']['mode'],'inner')
    def test_revisions_preserve_original_evidence(self):
        old=update_utterances({},[self.row()],10,[])
        new=update_utterances(old,[{**self.row(),'speaker':None,'mode':'inner','mode_status':'working'}],12,[])
        self.assertEqual(new['u1']['prior']['speaker'],'p1');self.assertEqual(old['u1']['speaker'],'p1')
        self.assertEqual(new['u1']['revision'],2);self.assertNotIn('prior',recent_utterances(new)[0])
    def test_future_and_unheard_audio_evidence_rejected(self):
        for row in ({**self.row(),'at':11},{**self.row(),'source':'audio','cue_id':'future'}):
            with self.assertRaises(ValueError):update_utterances({},[row],10,[])
    def test_claim_check_cannot_invent_quote(self):
        with self.assertRaises(ValueError):parse_check(json.dumps({'issues':[{'quote':'你说过','reason':'归属未知'}]}),'我很累')
        self.assertEqual(parse_check('{"issues":[]}','一种主观感受')['issues'],[])
    def test_no_claim_of_unavailable_audio_lipsync_evidence(self):
        with self.assertRaises(ValueError):update_utterances({},[{**self.row(),'evidence':['verified_lip_sync']}],10,[])
    def test_checker_agreement_cannot_promote_working_binding(self):
        ledger=update_utterances({},[self.row()],10,[])
        report={'issues':[],'bindings':[{'quote':'那个人说','utterance_id':'u1','kind':'speaker','asserted_as_fact':True,'value':'p1'}]}
        self.assertTrue(enforce_bindings(report,ledger,'那个人说他很累')['issues'][0]['enforced'])
        report['bindings'][0]['asserted_as_fact']=False
        self.assertEqual(enforce_bindings(report,ledger,'可能是那个人说的')['issues'],[])
        self.assertEqual(enforce_bindings({'issues':[],'bindings':[]},ledger,'找声音像捉迷藏')['issues'],[])

if __name__=='__main__':unittest.main()
