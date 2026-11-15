import unittest
from reaction_viewpoint import bootstrap_viewpoints,apply_updates,viewpoint_context
from reaction_relation_run import parse_choice


class ViewpointTests(unittest.TestCase):
    def test_silence_needs_no_summary_or_update(self):
        c=parse_choice('{"action":"watch_silently","text":"","reason":"继续看","listening_tradeoff":""}')
        self.assertEqual(c['viewpoint_updates'],[])
        s={'cursor':0};bootstrap_viewpoints(s)
        apply_updates(s,[{'id':'a','text':'我还想知道她为什么走','status':'active'}],1)
        apply_updates(s,[],2)
        self.assertEqual(viewpoint_context(s)['notes'][0]['updated_at'],1)

    def test_revision_and_retirement_preserve_original(self):
        s={'cursor':0};bootstrap_viewpoints(s)
        apply_updates(s,[{'id':'a','text':'有些怀疑','status':'active'}],1)
        apply_updates(s,[{'id':'a','text':'我改观了','status':'settled'}],2)
        self.assertEqual(s['viewpoint_history'][1]['before']['text'],'有些怀疑')
        self.assertEqual(len(s['viewpoints']),1)
        self.assertEqual(viewpoint_context(s)['recent_changes'][0]['after']['text'],'我改观了')

    def test_projection_budget_does_not_delete_records(self):
        s={'cursor':0};bootstrap_viewpoints(s)
        for i in range(20):apply_updates(s,[{'id':str(i),'text':'想法'*100,'status':'active'}],i)
        c=viewpoint_context(s,1000)
        self.assertGreater(c['omitted'],0);self.assertEqual(len(s['viewpoints']),20)
        import json
        self.assertLessEqual(len(json.dumps(c,ensure_ascii=False)),1000)

    def test_resume_does_not_duplicate_or_erase(self):
        s={'cursor':10,'attention':'还想继续看'};bootstrap_viewpoints(s);bootstrap_viewpoints(s)
        self.assertEqual(len(s['viewpoint_history']),1)


if __name__=='__main__':unittest.main()
