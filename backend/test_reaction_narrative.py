import json
import unittest
from reaction_narrative import parse_narrative,public_context,validate_public_choice,narrative_snapshot

class NarrativeTests(unittest.TestCase):
    def test_narrative_inference_does_not_require_voice_identity_and_keeps_revision(self):
        row={'id':'same-person','kind':'relation','claim':'独白可能延续同一人的视角','status':'tentative','confidence':.6,'evidence_at':[12]}
        state=parse_narrative(json.dumps({'account':'人物可能经历了身份变化，声纹仍未知','updates':[row]}),None,12)
        revised={**row,'claim':'新对白支持同一个叙述者','status':'revised','evidence_at':[15]}
        next_state=parse_narrative(json.dumps({'account':'关系有了新证据','updates':[revised]}),state,15)
        self.assertEqual(next_state['records']['same-person']['revision'],2)
        self.assertEqual(state['records']['same-person']['claim'],row['claim'])
        with self.assertRaises(ValueError):parse_narrative(json.dumps({'account':'future','updates':[{**row,'evidence_at':[20]}]}),state,15)
    def test_public_channel_does_not_include_private_audit_or_raw_visual_description(self):
        state={'narrative_state':{'account':'人物遇到改变','history':[{'private':'audit'}]},'experience_state':{'secret':'raw-frame'},'actor_attention':'想看看他接下来怎么办'}
        context=public_context(state,15,{'recent':[]},[])
        self.assertNotIn('audit',json.dumps(context));self.assertNotIn('raw-frame',json.dumps(context))
        self.assertEqual(context['story_so_far'],'人物遇到改变')
        self.assertEqual(validate_public_choice({'action':'continue','text':''})['action'],'continue')
        for delivery in ('overlay','pause'):
            self.assertEqual(validate_public_choice({'action':'speak','text':'这句话由她决定。','delivery':delivery})['delivery'],delivery)
        with self.assertRaises(ValueError):validate_public_choice({'action':'continue','text':'queued words'})
    def test_identity_is_not_displaced_by_many_recent_frame_events(self):
        records={'person':{'kind':'entity','updated_at':1,'claim':'same child'}}
        records.update({str(i):{'kind':'event','updated_at':i,'claim':'frame'} for i in range(2,60)})
        selected=narrative_snapshot({'records':records})
        self.assertTrue(any(r['kind']=='entity' for r in selected['records']))
        self.assertGreater(selected['omitted'],0)

if __name__=='__main__':unittest.main()
