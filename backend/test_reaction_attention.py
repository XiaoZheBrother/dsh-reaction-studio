import json
import unittest
from reaction_attention import heard_until, parse_observation, speech_awareness, turn_signal


class AttentionTests(unittest.TestCase):
    def test_audio_never_leaks_future_chunk_context(self):
        data={'cues':[{'id':'a','end':3,'available_at':12},{'id':'b','end':14,'available_at':24}]}
        self.assertEqual(heard_until(data,4),[])
        self.assertEqual([c['id'] for c in heard_until(data,12)],['a'])

    def test_completed_unit_is_not_reconsidered_every_frame(self):
        o={'unit_id':'conversation','boundary':'open','unexpected_change':False,'change':'new camera angle'}
        self.assertIsNone(turn_signal(o,[]))
        o['boundary']='complete'
        signal=turn_signal(o,[])
        self.assertIsNone(turn_signal(o,[signal]))

    def test_spontaneous_change_is_possible_without_time_cooldown(self):
        o={'unit_id':'scene','boundary':'open','unexpected_change':True,'change':'new event'}
        self.assertIsNotNone(turn_signal(o,[]))

    def test_voice_occupancy_counts_elapsed_audio_only(self):
        es=[{'audio':'a','text':'previous','cursor':2,'output_at':2,'duration':8},
            {'audio':'b','text':'current','cursor':12,'output_at':12,'duration':8}]
        result=speech_awareness(es,15)
        self.assertEqual(result['since_last_finished'],0)
        self.assertEqual(result['windows'][0]['spoken_seconds'],11)
        self.assertEqual(result['recent'][-1]['text'],'current')

    def test_visible_person_cannot_be_assigned_as_speaker(self):
        o={'unit_id':'a','boundary':'open','unexpected_change':False,'understanding':'x','change':'',
           'attributions':[{'cue_id':'c','character':'person onscreen','confidence':.9,'evidence':['visible_only'],'reason':'visible'}]}
        result=parse_observation(json.dumps(o),[{'id':'c'}])
        self.assertIsNone(result['attributions'][0]['character'])
        self.assertEqual(result['attributions'][0]['confidence'],0)
        rejected=parse_observation(json.dumps(o),[])
        self.assertEqual(rejected['attributions'],[])
        self.assertIsNone(rejected['rejected_attributions'][0]['character'])


if __name__=='__main__':unittest.main()
