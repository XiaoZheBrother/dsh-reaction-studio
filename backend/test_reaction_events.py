import unittest
from reaction_events import envelope, validate_reply, scene_prefix

class EventTests(unittest.TestCase):
    def test_subtitles_cannot_become_viewer_message(self):
        event=envelope({'subtitle':'你觉得呢？','own_speech':'你问我'},42)
        self.assertEqual(event['viewer_messages'],[])
        with self.assertRaises(ValueError):validate_reply({'reply_to_message_id':'invented'},[])
        self.assertEqual(validate_reply({'text':'好有趣','reply_to_message_id':None},[] )['text'],'好有趣')

    def test_actual_viewer_can_be_addressed_without_promoting_media(self):
        e=envelope({'subtitle':'hello'},42,[{'id':'real-1','text':'你怎么看？'}])
        self.assertEqual(validate_reply({'reply_to_message_id':'real-1'},e['viewer_messages'])['reply_to_message_id'],'real-1')

    def test_scene_override_preserves_global_switch_and_original(self):
        p={'enabled':False,'prefix':'old'}
        out=scene_prefix(p,{'reaction_prefix':'我正在看这部剧喵……'})
        self.assertFalse(out['enabled']);self.assertEqual(p['prefix'],'old')
        self.assertEqual(scene_prefix(p,{}),p)
