import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import reaction_relation_run as runner


class RunnerTests(unittest.TestCase):
    def test_private_viewpoint_survives_silence_and_is_only_in_actor_context(self):
        contexts=[]
        class Engine:
            def __init__(self,*a,**k):self.calls=0;self.usage=0
            async def complete(self,messages,key):
                self.calls+=1
                ctx=json.loads(messages[1]['content'][0]['text']);ctx=ctx.get('media_observation',ctx);contexts.append((self.stage,ctx))
                if self.stage=='relation_observation':return ['{"nodes":[],"links":[]}']
                out={'action':'watch_silently','text':'','reason':'继续看','listening_tradeoff':''}
                if ctx['viewed_through']==2:out['viewpoint_updates']=[{'id':'curiosity','text':'我想知道她会不会回来','status':'active'}]
                return [json.dumps(out)]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(1,25):(root/f'{i:06d}.jpg').write_bytes(b'test')
            (root/'hearing.json').write_text('{"cues":[]}')
            job=dict(output=str(root/'out'),home=tmp,persona=tmp,frames=tmp,hearing=str(root/'hearing.json'),seconds=6,voice_chars_per_second=5)
            with patch.object(runner,'Reactor',Engine),patch.object(runner.generator,'load_context',return_value=([{'content':'p'}],{},'key')):
                asyncio.run(runner.run(job))
            actors=[c for stage,c in contexts if stage=='relation_decision']
            self.assertEqual(actors[-1]['your_viewing_perspective']['notes'][0]['updated_at'],2)
            self.assertTrue(all('your_viewing_perspective' not in c for stage,c in contexts if stage=='relation_observation'))
            state=json.loads((root/'out/trace.json').read_text('utf-8'))
            self.assertEqual(len(state['viewpoint_history']),1)
            self.assertTrue(all(d['text']=='' for d in state['decisions']))

    def test_speech_not_sent_through_second_arrangement(self):
        stages=[]
        class Engine:
            def __init__(self,*a,**k):self.calls=0;self.usage=0
            async def complete(self,messages,key):
                self.calls+=1;stages.append(self.stage)
                if self.stage=='relation_observation':return ['{"nodes":[],"links":[]}']
                if self.stage=='relation_claim_check':return ['{"claims":[]}']
                return [json.dumps({'action':'speak_over_video','text':'好可爱呀','attention':'','reason':'自己的感受','listening_tradeoff':''})]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(1,9):(root/f'{i:06d}.jpg').write_bytes(b'test')
            (root/'hearing.json').write_text('{"cues":[]}')
            job=dict(output=str(root/'out'),home=tmp,persona=tmp,frames=tmp,hearing=str(root/'hearing.json'),seconds=2,voice_chars_per_second=5)
            with patch.object(runner,'Reactor',Engine),patch.object(runner.generator,'load_context',return_value=([{'content':'p'}],{},'key')):
                asyncio.run(runner.run(job))
            state=json.loads((root/'out/trace.json').read_text('utf-8'))
            self.assertEqual(state['decisions'][0]['text'],'好可爱呀')
            self.assertEqual(stages,['relation_observation','relation_decision','relation_claim_check'])

    def test_alignment_is_not_reinjected_but_raw_evidence_survives(self):
        row={'id':'audio:a','at':1,'available_at':2,'cue':{'text':'hello','speaker_id':None,'words':[{'start':1,'end':2}]}}
        compact=runner.evidence_context([row])[0]
        self.assertNotIn('words',compact['cue']);self.assertIn('words',row['cue'])
        self.assertEqual(compact['available_at'],2);self.assertIsNone(compact['cue']['speaker_id'])

    def test_real_entry_contract_keeps_prefix_and_silence_and_no_future_audio(self):
        seen=[]
        class Engine:
            def __init__(self,*args,**kwargs):self.calls=0;self.usage=0
            async def complete(self,messages,key):
                self.calls+=1;self.usage+=10;seen.append(messages)
                if self.stage=='relation_observation':return [json.dumps({'nodes':[],'links':[]})]
                return [json.dumps({'action':'watch_silently','text':'','reason':'先看','attention':'','listening_tradeoff':''})]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);frames=root/'frames';frames.mkdir()
            for i in range(1,9):(frames/f'{i:06d}.jpg').write_bytes(b'test')
            hearing=root/'hearing.json';hearing.write_text(json.dumps({'cues':[{'id':'future','start':1,'end':5,'available_at':6,'text':'FUTURE_SECRET'}]}))
            job=dict(output=str(root/'records'),home=tmp,persona=tmp,frames=str(frames),hearing=str(hearing),seconds=2,voice_chars_per_second=5,reaction_prefix='VIEWING_PREFIX')
            with patch.object(runner,'Reactor',Engine),patch.object(runner.generator,'load_context',return_value=([{'content':'PERSONA'}],{'enabled':True,'prefix':'PREFIX'},'test-key')):
                asyncio.run(runner.run(job))
            state=json.loads((root/'records'/'trace.json').read_text('utf-8'))
            self.assertTrue(state['complete']);self.assertEqual(state['decisions'][0]['action'],'continue')
            self.assertEqual(state['calls'],2)
            self.assertEqual(seen[0][-1]['reasoning_content'],'PREFIX')
            self.assertEqual(seen[-1][-1]['reasoning_content'],'VIEWING_PREFIX')
            incoming=json.loads(seen[-1][1]['content'][0]['text'])
            self.assertEqual(incoming['event']['kind'],'media_observation')
            self.assertEqual(incoming['viewer_messages'],[])
            self.assertIn('PERSONA',seen[-1][0]['content'])
            self.assertNotIn('FUTURE_SECRET',json.dumps(seen))
            self.assertFalse(list(root.glob('*.mp3')))

    def test_invalid_observation_failure_rolls_back_interval(self):
        class Engine:
            def __init__(self,*args,**kwargs):self.calls=0;self.usage=0
            async def complete(self,*args,**kwargs):
                self.calls+=1;self.usage+=10;return ['not json']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(1,9):(root/f'{i:06d}.jpg').write_bytes(b'test')
            (root/'hearing.json').write_text('{"cues":[]}')
            job=dict(output=str(root/'out'),home=tmp,persona=tmp,frames=tmp,hearing=str(root/'hearing.json'),seconds=2,voice_chars_per_second=5)
            with patch.object(runner,'Reactor',Engine),patch.object(runner.generator,'load_context',return_value=([{'content':'p'}],{},'key')):
                with self.assertRaises(ValueError):asyncio.run(runner.run(job))
            state=json.loads((root/'out'/'trace.json').read_text('utf-8'))
            self.assertEqual(state['cursor'],0);self.assertEqual(state['wall'],0)
            self.assertEqual(state['graph']['evidence'],{});self.assertEqual(state['calls'],2)
            self.assertTrue((root/'out'/'failed-interval.json').exists())


if __name__=='__main__':unittest.main()
