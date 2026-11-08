import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import reaction_offline
from reaction_intent import parse_intent
from reaction_render import caption_groups,caption_pages

class OfflineDecisionTests(unittest.TestCase):
    def test_continue_does_not_generate_or_synthesize_a_reply(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'frames').mkdir()
            for i in range(15):(root/'frames'/f'{i:05d}.jpg').write_bytes(b'jpeg')
            (root/'timeline.json').write_text(json.dumps({'source':'source.mp4','seconds':15,'step':15,'events':[]}),encoding='utf-8')
            calls=[]
            class Engine:
                async def complete(self,messages,key):
                    calls.append(messages)
                    return json.dumps({'action':'continue','focus_at':0,'reason':'keep watching'}),1
            args=SimpleNamespace(output=root,video=Path('source.mp4'),home=root,persona=root/'persona',seconds=15,step=15,resume=True)
            with patch('reaction_offline.generator.load_context',return_value=([{'role':'system','content':'persona'}],{'enabled':True,'prefix':'same'},'test')), patch('reaction_offline.Reactor',return_value=Engine()), patch('reaction_offline.subprocess.run',return_value=SimpleNamespace(stderr='Duration: 00:01:00.00')), patch('reaction_offline.edge_tts.Communicate',side_effect=AssertionError('silent must not synthesize')):
                asyncio.run(reaction_offline.run(args))
            result=json.loads((root/'timeline.json').read_text(encoding='utf-8'))['events'][0]
            self.assertEqual(len(calls),1)
            self.assertEqual(result['action'],'silent')
            self.assertNotIn('audio',result)
            self.assertEqual(calls[0][-1]['reasoning_content'],'same')

    def test_future_visual_reference_is_rejected(self):
        with self.assertRaises(ValueError):parse_intent('{"action":"speak","focus_at":16}',0,15)

    def test_subtitles_use_actual_word_timing_not_equal_text_slices(self):
        words=[{'type':'WordBoundary','offset':10000000,'duration':2000000,'text':'短'}, {'type':'WordBoundary','offset':40000000,'duration':15000000,'text':'长句'}]
        self.assertEqual(caption_groups(words),[(1,1.2,'短'),(4,5.5,'长句')])
        with self.assertRaises(ValueError):caption_groups([])

class CaptionPageTests(unittest.TestCase):
    def test_long_fitting_utterance_stays_on_one_page_with_punctuation(self):
        text='这是一段长句，'+('可以在同一屏里换行，'*8)+'说完再消失。'
        words=[{'type':'WordBoundary','offset':1000000,'duration':180000000,'text':text}]
        pages=caption_pages(text,words)
        self.assertEqual(len(pages),1)
        self.assertEqual(pages[0]['text'],text)
        self.assertEqual(pages[0]['start'],0)
    def test_overflow_pages_use_word_times_and_keep_every_character(self):
        text='甲'*40+'。'+'乙'*40+'。'+'丙'*40+'。'
        words=[{'type':'WordBoundary','offset':i*1000000,'duration':1000000,'text':c} for i,c in enumerate(text) if c!='。']
        pages=caption_pages(text,words,capacity=45)
        self.assertEqual(''.join(p['text'] for p in pages),text)
        self.assertEqual(len(pages),3)
        self.assertAlmostEqual(pages[1]['start'],4.1)
        self.assertAlmostEqual(pages[0]['end'],4.1)

if __name__=='__main__':unittest.main()
