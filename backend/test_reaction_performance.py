import unittest,json,subprocess
from pathlib import Path
from reaction_performance import validate_performance
class PerformanceTests(unittest.TestCase):
    def test_no_command_does_not_invent_emotion(self):
        v=validate_performance(None)
        self.assertEqual((v['expression'],v['motion']),('keep','none'))
    def test_choice_is_preserved_without_scene_mapping(self):
        for expression,motion in [('neutral','point'),('流冷汗','none'),('微笑','shake_head')]:
            v={'expression':expression,'motion':motion,'duration':4,'reason':'my choice'}
            self.assertEqual(validate_performance(v),v)
    def test_unsupported_and_invalid_commands_are_rejected(self):
        for v in [{'motion':'walk'},{'expression':'脱鞋'},{'duration':float('nan')},{'duration':True},{'duration':100}]:
            with self.subTest(v=v),self.assertRaises(ValueError):validate_performance(v)
if __name__=='__main__':unittest.main()
