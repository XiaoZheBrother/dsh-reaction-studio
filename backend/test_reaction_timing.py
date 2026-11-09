import unittest
from reaction_timing import validate_timing

class TimingTests(unittest.TestCase):
    def test_no_constant_delay_is_added(self):
        for ready,understood,start in [(10,10.2,10.6),(30,31.1,32.8)]:
            result=validate_timing({'understood_at':understood,'speak_at':start,'reason':'actor choice'},evidence_ready=ready,considered_at=ready,source_end=40)
            self.assertEqual(result['speak_at'],start)
    def test_cannot_speak_before_reading_or_backdate(self):
        for understood,start in [(9,11),(11,11),(11,10),(12,50)]:
            with self.assertRaises(ValueError):
                validate_timing({'understood_at':understood,'speak_at':start,'reason':'x'},evidence_ready=10,considered_at=11,source_end=40)

if __name__=='__main__':unittest.main()
