import copy
import unittest
from reaction_relations import apply_graph, empty_graph, graph_context, review_relation, check_claims, ingest_observation
from reaction_relations import check_public_claims, viewing_context


def evidence(key='e', at=1):
    return {'id':key,'at':at,'available_at':at,'modality':'visual'}


def node(key, kind):
    return {'id':key,'kind':kind,'label':key,'sources':['e']}


def link(key, a, p, b, **kw):
    return dict(id=key, subject=a, predicate=p, object=b, status='supported',
                basis='observation', reason='observed', support=['e'], against=[], depends_on=[], **kw)


def scene():
    return apply_graph(None,[evidence()],{'nodes':[node('body','visual'),node('other','visual'),
        node('mind','subject'),node('voice','voice'),node('u','utterance'),node('a','action')],
        'links':[link('action','a','performed_by','body')]},1)


class RelationTests(unittest.TestCase):
    def test_public_unknown_and_feelings_are_not_false(self):
        for kind in ('fact','hypothesis','feeling'):
            r=check_public_claims(scene(),'她是在哄人吗',[{'quote':'她是在哄人吗','kind':kind,'requires':['unresolved']}])
            self.assertEqual(r['issues'],[])
            self.assertTrue(r['private_uncertainties'])

    def test_only_asserted_conflict_blocks(self):
        g=apply_graph(scene(),[],{'links':[link('speaker','u','spoken_by','body')]},2)
        claim={'quote':'是另一个人说的','kind':'fact','asserted_relations':[{'subject':'u','predicate':'spoken_by','object':'other'}]}
        self.assertTrue(check_public_claims(g,claim['quote'],[claim])['issues'])
        claim['kind']='hypothesis'
        self.assertFalse(check_public_claims(g,claim['quote'],[claim])['issues'])

    def test_actor_does_not_receive_auditor_metadata(self):
        c=viewing_context(scene(),1)
        self.assertNotIn('voice',{n['kind'] for n in c['events_and_people']})
        self.assertNotIn('reason',c['working_connections'][0])
        self.assertNotIn('dependency_versions',c['working_connections'][0])
    def test_bad_link_does_not_discard_independent_action(self):
        good=link('good','u','spoken_by','body')
        bad=link('bad','u','voiced_by','missing_voice')
        g,rejected=ingest_observation(scene(),{'links':[bad,good]},2)
        self.assertIn('good',g['links']);self.assertNotIn('bad',g['links'])
        self.assertEqual(rejected[0]['proposal'],bad)

    def test_node_revision_invalidates_related_link(self):
        updated=node('body','visual');updated['reidentify']=True
        g=apply_graph(scene(),[],{'nodes':[updated]},2)
        self.assertEqual(g['links']['action']['status'],'needs_review')

    def test_descriptive_update_preserves_identity(self):
        updated=node('body','visual');updated['label']='同一人现在站起来了'
        g=apply_graph(scene(),[],{'nodes':[updated]},2)
        self.assertEqual(g['links']['action']['status'],'supported')

    def test_quarantined_dependency_not_promoted(self):
        x=link('bad','u','spoken_by','missing')
        y=link('dependent','u','first_person','mind');y['depends_on']=['bad']
        g,errors=ingest_observation(scene(),{'links':[y,x]},2)
        self.assertNotIn('dependent',g['links']);self.assertEqual(len(errors),2)

    def test_types_cannot_collapse(self):
        g=scene()
        with self.assertRaises(ValueError):apply_graph(g,[],{'nodes':[node('body','voice')]},2)
        with self.assertRaises(ValueError):apply_graph(g,[],{'links':[link('bad','u','spoken_by','mind')]},2)

    def test_cooccurrence_not_identity(self):
        r=link('s','u','spoken_by','body');r['basis']='cooccurrence'
        g=apply_graph(scene(),[],{'links':[r]},2)
        self.assertEqual(g['links']['s']['status'],'tentative')

    def test_revision_invalidates_transitive_dependents(self):
        x=link('x','u','first_person','mind')
        y=link('y','mind','embodied_as','body');y['depends_on']=['x']
        z=link('z','u','spoken_by','body');z['depends_on']=['y']
        old=apply_graph(scene(),[],{'links':[x,y,z]},2)
        x['status']='rejected'
        g=apply_graph(old,[],{'links':[x]},3)
        self.assertEqual(old['links']['z']['status'],'supported')
        self.assertEqual(g['links']['z']['status'],'needs_review')
        self.assertEqual(g['links']['y']['status'],'needs_review')
        self.assertGreaterEqual(len(g['history']),3)
        x['status']='supported'
        fixed=apply_graph(g,[],{'links':[x,y,z]},4)
        self.assertEqual(fixed['links']['z']['status'],'supported')

    def test_atomic_reject_future_and_changed_raw(self):
        g=scene();before=copy.deepcopy(g)
        for ev in ([evidence('future',3)],[dict(evidence(),modality='audio')]):
            with self.assertRaises(ValueError):apply_graph(g,ev,{},2)
        self.assertEqual(g,before)

    def test_cycles_rejected_atomically(self):
        x=link('x','u','first_person','mind');x['depends_on']=['y']
        y=link('y','mind','embodied_as','body');y['depends_on']=['x']
        with self.assertRaises(ValueError):apply_graph(scene(),[],{'links':[x,y]},2)

    def test_hearing_is_not_performing(self):
        g=apply_graph(scene(),[],{'links':[link('h','u','heard_by','body')]},2)
        claim={'quote':'他刚说完就挥手','kind':'fact','references':['u','a'],'requires':[], 'same_actor':True}
        self.assertTrue(check_claims(g,claim['quote'],[claim])['issues'])
        g=apply_graph(g,[],{'links':[link('f','u','first_person','mind'),link('b','mind','embodied_as','body')]},3)
        self.assertFalse(check_claims(g,claim['quote'],[claim])['issues'])

    def test_simple_action_and_feeling_not_blocked_by_unknown_voice(self):
        g=scene()
        claims=[{'quote':'他在挥手','kind':'fact','references':['a','body'],'requires':['action']},
                {'quote':'好开心','kind':'feeling','references':[],'requires':[]}]
        self.assertFalse(check_claims(g,'他在挥手，好开心',claims)['issues'])

    def test_review_only_past_and_bounded(self):
        g=scene();r=review_relation(g,['action'],1,4)
        self.assertTrue(all(0<=w['start']<=w['end']<=1 for w in r['replay_windows']))
        with self.assertRaises(ValueError):review_relation(g,['action'],0)
        with self.assertRaises(ValueError):review_relation(g,['action'],1,100)

    def test_budget_keeps_whole_dependencies(self):
        x=link('x','u','first_person','mind')
        y=link('y','mind','embodied_as','body');y['depends_on']=['x']
        g=apply_graph(scene(),[],{'links':[x,y]},2)
        c=graph_context(g,2,900);ids={r['id'] for r in c['links']}
        for r in c['links']:self.assertTrue(set(r['depends_on'])<=ids)
        self.assertEqual(len(g['links']),3)

    def test_duplicate_nodes_and_string_boolean_rejected(self):
        with self.assertRaises(ValueError):apply_graph(scene(),[],{'nodes':[node('n','visual')]*2},2)
        with self.assertRaises(ValueError):check_claims(scene(),'x',[{'quote':'x','same_actor':'false'}])


if __name__=='__main__':unittest.main()
