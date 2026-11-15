import unittest
from unittest.mock import patch
from reaction_afterword import relation_afterword_state


class RelationReflectionTests(unittest.TestCase):
    def test_unfinished_run_cannot_be_treated_as_finished_episode(self):
        for trace in ({'complete':False,'cursor':1420}, {'complete':True,'cursor':504}):
            with self.assertRaises(ValueError):
                relation_afterword_state(trace,{'seconds':1420,'hearing':'hearing.json'})

    @patch('reaction_relations.viewing_context',return_value={'evidence':'this run'})
    def test_reflection_uses_current_run_reactions_and_viewpoints(self,context):
        trace={'complete':True,'cursor':1420,'graph':{},
               'decisions':[{'cursor':6,'text':''},{'cursor':12,'text':'自己的反应'}],
               'viewpoints':{'one':{'text':'现在的想法'}}}
        state=relation_afterword_state(trace,{'seconds':1420,'hearing':'hearing.json'})
        self.assertEqual(state['plot_memory']['your_reactions_from_this_run'],[{'at':12,'text':'自己的反应'}])
        self.assertEqual(state['plot_memory']['your_viewpoints_from_this_run'],[{'text':'现在的想法'}])
        context.assert_called_once_with({},1420,5000)
