import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import reaction_trace_dub as dub


class TraceDubTests(unittest.TestCase):
    def test_long_overlay_does_not_trigger_replanning_but_actual_overlap_does(self):
        for next_cursor,expected_calls in [(330,0),(309,1)]:
            with self.subTest(next_cursor=next_cursor),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                def write(name,obj):
                    p=root/name;p.write_text(json.dumps(obj),encoding='utf-8');return p
                job=write('job.json',{'home':tmp,'persona':tmp,'seconds':504,'start_seconds':300})
                trace=write('trace.json',{'complete':True,'decisions':[
                    {'cursor':306,'action':'speak','text':'长话也遵从继续播放','reason':'想边看边说'},
                    {'cursor':next_cursor,'action':'speak','text':'下一句','reason':'继续播放'}]})
                review=write('review.json',{'status':'accepted_for_preview','trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest()})
                prod=write('prod.json',{'voice_studio':{}});voice=root/'voice.wav';voice.write_bytes(b'test')
                async def prepare(*args):return {'duration':20,'path':str(voice),'subtitles':[{'start':0,'end':7,'text':args[0][:2]},{'start':7,'end':20,'text':args[0][2:]}]}
                stages=[]
                class Engine:
                    def __init__(self,*a,**k):pass
                    async def complete(self,*args):
                        stages.append(self.stage)
                        return ['{"action":"wait_while_playing","reason":"原片继续，等自己上一句结束"}']
                a=SimpleNamespace(job=job,trace=trace,review=review,production=prod,output=root/'out')
                with patch.object(dub,'Reactor',Engine),patch.object(dub.generator,'load_context',return_value=([{'content':'persona'}],{},'key')),patch.object(dub,'prepare_voice',prepare):
                    asyncio.run(dub.main(a))
                state=json.loads((a.output/'viewing-state.json').read_text('utf-8'))
                self.assertEqual(state['pauses'],[])
                self.assertEqual(stages,['playback_conflict']*expected_calls)
                self.assertEqual(state['events'][1]['output_at'],max(26,next_cursor-300))
                self.assertEqual(state['events'][0]['captions'][0]['end'],7)
                self.assertEqual(''.join(c['text'] for c in state['events'][0]['captions']),'长话也遵从继续播放')

    def test_review_hash_and_measured_pause_preserve_words_and_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,obj):
                p=root/name;p.write_text(json.dumps(obj),encoding='utf-8');return p
            job=write('job.json',{'home':tmp,'persona':tmp,'seconds':504,'start_seconds':300})
            trace=write('trace.json',{'complete':True,'decisions':[
                {'cursor':306,'action':'pause','text':'原话不改','reason':'想暂停说'},
                {'cursor':312,'action':'continue','text':'','reason':'接着看'}]})
            review=write('review.json',{'status':'accepted_for_preview','trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest()})
            prod=write('prod.json',{'voice_studio':{}});voice=root/'voice.wav';voice.write_bytes(b'test')
            async def prepare(*args):return {'duration':2.5,'path':str(voice),'subtitles':[{'start':0,'end':2.5,'text':args[0]}]}
            class Engine:
                def __init__(self,*a,**k):pass
            a=SimpleNamespace(job=job,trace=trace,review=review,production=prod,output=root/'out')
            with patch.object(dub,'Reactor',Engine),patch.object(dub.generator,'load_context',return_value=([{'content':'persona'}],{},'key')),patch.object(dub,'prepare_voice',prepare):
                asyncio.run(dub.main(a))
            state=json.loads((root/'out/viewing-state.json').read_text('utf-8'))
            self.assertEqual(state['events'][0]['text'],'原话不改')
            self.assertEqual(state['events'][0]['output_at'],6)
            self.assertEqual(state['pauses'][0]['source'],6)
            self.assertEqual(state['performances'][1]['wall'],14.5)
            snapshots=[]
            real_save=dub.save
            def record_save(path,value):
                if path.name=='viewing-state.json':snapshots.append(len(value['events']))
                real_save(path,value)
            with patch.object(dub,'Reactor',Engine),patch.object(dub.generator,'load_context',return_value=([{'content':'persona'}],{},'key')),patch.object(dub,'prepare_voice',prepare),patch.object(dub,'save',record_save):
                asyncio.run(dub.main(a))
            self.assertTrue(snapshots)
            self.assertTrue(all(count==2 for count in snapshots),'resume must not roll renderer checkpoint back')
            trace.write_text('{}')
            with self.assertRaises(ValueError):asyncio.run(dub.main(a))


if __name__=='__main__':unittest.main()
