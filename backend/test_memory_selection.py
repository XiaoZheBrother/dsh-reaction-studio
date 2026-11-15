import unittest
import json
import copy
from reaction_context import pack_messages
from reaction_memory_selection import select_optional_memories

class MemorySelectionTests(unittest.TestCase):
    def test_relevance_precedes_filename_and_repeated_memory_is_not_evidence(self):
        data={'memory':[{'source':'z','text':'今天下雨'},{'source':'a','text':'工程师占领油田'},{'source':'copy','text':'工程师占领油田'}],
              'hearing':[{'text':'重复对白'},{'text':'重复对白'}]}
        count=select_optional_memories([data],'工程师')
        self.assertEqual(count,1)
        self.assertEqual(data['memory'][-1]['source'],'a')
        self.assertEqual(len(data['hearing']),2)
    def test_budget_rejects_unrelated_memory_first_without_mutating_sources(self):
        marker='以下是只读记忆资料；写稿要求和写稿表达偏好不在本场景加载：\n'
        memory={'memory':[{'source':'old-important','text':'油田经济经验'*150},{'source':'new-unrelated','text':'吃饭睡觉'*200}]}
        messages=[{'role':'system','content':'PERSONA\n'+marker+json.dumps(memory,ensure_ascii=False)},
                  {'role':'user','content':'油田经济经验'},
                  {'role':'assistant','prefix':True,'content':'','reasoning_content':'PREFIX'}]
        original=copy.deepcopy(messages)
        packed,report=pack_messages(messages,budget=6700)
        body=json.loads(packed[0]['content'].split(marker)[1])
        self.assertEqual([x['source'] for x in body['memory']],['old-important'])
        self.assertLessEqual(report['estimated_input'],report['input_limit'])
        self.assertEqual(messages,original);self.assertEqual(packed[-1],original[-1])

if __name__=='__main__':unittest.main()
