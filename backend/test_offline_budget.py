import copy
import unittest
from reaction_context import pack_messages, summary_batch

class OfflineBudgetTests(unittest.TestCase):
    def test_afterword_budgets_past_speech_without_dropping_review_or_viewpoints(self):
        import json
        obj={'viewing_evidence':{'latest_memory':{
            'your_reactions_from_this_run':[{'at':i,'text':'old speech '*1000} for i in range(70)],
            'your_viewpoints_from_this_run':[{'text':'my evolving opinion'}]}},
            'review_evidence':[{'source':24,'note':'uncertain identity from reviewed audio'}]}
        original=copy.deepcopy(obj)
        packed,report=pack_messages([{'role':'user','content':json.dumps(obj)}],budget=6000,output_reserve=1000)
        out=json.loads(packed[0]['content'][0]['text'])
        self.assertEqual(out['review_evidence'],original['review_evidence'])
        self.assertEqual(out['viewing_evidence']['latest_memory']['your_viewpoints_from_this_run'],original['viewing_evidence']['latest_memory']['your_viewpoints_from_this_run'])
        self.assertEqual(obj,original)
        self.assertLessEqual(report['estimated_input'],report['input_limit'])

    def test_older_own_speech_is_budgeted_but_latest_and_playing_are_kept(self):
        import json
        rows=[{'text':'旧话'*1000,'remaining':0} for _ in range(8)]
        rows.append({'text':'刚说的话','remaining':0})
        active=[{'text':'正在说','remaining':2}]
        obj={'media_observation':{'own_speech':{'recent':rows,'currently_speaking':active}}}
        messages=[{'role':'user','content':json.dumps(obj,ensure_ascii=False)}]
        before=copy.deepcopy(messages)
        packed,report=pack_messages(messages,budget=6000,output_reserve=1000)
        data=json.loads(packed[0]['content'][0]['text'])['media_observation']['own_speech']
        self.assertEqual(data['recent'],[rows[-1]])
        self.assertEqual(data['currently_speaking'],active)
        self.assertEqual(messages,before)
        self.assertEqual(report['omitted']['media_observation.own_speech.recent'],8)

    def test_active_own_speech_is_not_removed_to_fit(self):
        import json
        obj={'own_speech':{'recent':[{'text':'x'*9000,'remaining':3},{'text':'latest','remaining':0}]}}
        with self.assertRaisesRegex(ValueError,'Required context'):
            pack_messages([{'role':'user','content':json.dumps(obj)}],budget=6000,output_reserve=1000)

    def test_history_projection_preserves_source_and_protected_context(self):
        import json
        obj={'cursor':42,'hearing':[{'id':'heard','end':41,'text':'current words'}],
             'previous_unit':{'unit_id':'u','understanding':'uncertain','updates':[{'claim':'x'*4000}]},
             'recent_observations':[{'understanding':'old'*500,'updates':[{'claim':'nested'*1000}]} for _ in range(12)],
             'continuous_understanding':{'records':[{'id':str(i),'claim':'x'*1500} for i in range(24)]}}
        messages=[{'role':'system','content':'persona unchanged'},
                  {'role':'user','content':[{'type':'text','text':json.dumps(obj)},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,AAAA'}}]},
                  {'role':'assistant','content':'','prefix':True,'reasoning_content':'prefix unchanged'}]
        original=copy.deepcopy(messages)
        packed,report=pack_messages(messages,budget=18000)
        self.assertEqual(messages,original)
        self.assertEqual(packed[0],messages[0]);self.assertEqual(packed[-1],messages[-1])
        data=json.loads(packed[1]['content'][0]['text'])
        self.assertEqual(data['hearing'],obj['hearing'])
        self.assertEqual(data['cursor'],42)
        self.assertNotIn('updates',data['previous_unit'])
        self.assertTrue(report['omitted'])
        self.assertLessEqual(report['estimated_input'],report['input_limit'])
        self.assertEqual(packed[1]['content'][1],messages[1]['content'][1])
    def test_required_oversize_fails_without_mutation(self):
        messages=[{'role':'system','content':'x'*30000}]
        with self.assertRaisesRegex(ValueError,'Required context'):
            pack_messages(messages)
        self.assertEqual(len(messages[0]['content']),30000)
    def test_no_omission_when_small(self):
        _,report=pack_messages([{'role':'user','content':'current thought'}])
        self.assertEqual(report['omitted'],{})
    def test_memory_projection_preserves_persona_prefix_and_appended_rules(self):
        import json
        marker='以下是只读记忆资料；写稿要求和写稿表达偏好不在本场景加载：\n'
        system='original persona\n'+marker+json.dumps({'memory':[{'source':str(i),'text':'中'*2500} for i in range(8)]},ensure_ascii=False)+'\noriginal tool rules'
        messages=[{'role':'system','content':system},{'role':'user','content':'current evidence'},
                  {'role':'assistant','prefix':True,'content':'','reasoning_content':'original prefix'}]
        result,report=pack_messages(messages,budget=36000)
        self.assertTrue(result[0]['content'].startswith('original persona\n'+marker))
        self.assertTrue(result[0]['content'].endswith('\noriginal tool rules'))
        self.assertEqual(result[-1],messages[-1]);self.assertEqual(messages[0]['content'],system)
        self.assertGreater(report['omitted'].get('memory',0)+report['omitted'].get('duplicate_memory',0),0)
    def test_summary_coverage_is_contiguous_not_silently_skipped(self):
        events=[{'cursor':i,'story':'中'*400,'interest':'test'} for i in range(24)]
        selected=summary_batch(events,byte_budget=4000)
        self.assertGreater(len(selected),0);self.assertLess(len(selected),24)
        self.assertEqual(selected,events[:len(selected)])
    def test_usage_keeps_truncated_output_and_unknown_transport_cost(self):
        import tempfile,json
        from pathlib import Path
        from reaction_usage import usage_report
        with tempfile.TemporaryDirectory() as folder:
            rows=[{'stage':'observation','finish_reason':'length','usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_cache_hit_tokens':30}},
                  {'stage':'observation','finish_reason':'request_failed','usage':None}]
            Path(folder,'model-usage.jsonl').write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf8')
            report=usage_report(folder)['stages']['observation']
            self.assertEqual(report['requests'],2);self.assertEqual(report['reported_requests'],1)
            self.assertEqual(report['failed_outputs'],2);self.assertEqual(report['total_tokens'],120)
            self.assertEqual(report['cached_input_tokens'],30)
