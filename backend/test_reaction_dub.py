import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from reaction_dub import main,parse_delivery

class DubbingTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_delivery_rejected(self):
        for vector in ([0]*7,[float('nan')]*8,[True]*8):
            with self.assertRaises(ValueError):parse_delivery(json.dumps({'intent':'my choice','emotion_vector':vector}))

    async def test_measured_pause_rebuilds_clock_without_modifying_observations(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);view=root/'view';view.mkdir();workspace=root/'audio';workspace.mkdir()
            generated=workspace/'generated';generated.mkdir();(generated/'gen-test.wav').write_bytes(b'test')
            source={'complete':True,'input':{'seconds':180},'events':[{'id':0,'cursor':10,'text':'my words','audio':'deferred.wav','duration_estimated':True,'performance':None},{'id':1,'cursor':20,'action':'continue','performance':None}],'tool_receipts':[{'call_id':'old'}]}
            data=json.dumps(source);(view/'viewing-state.json').write_text(data)
            cfg=root/'config.json';cfg.write_text(json.dumps({'workspace':str(workspace)}))
            outputs=iter([json.dumps({'intent':'actor tone','emotion_vector':[0]*7+[.5]}),json.dumps({'choice':'pause','reason':'discuss this moment','text':''})])
            class Engine:
                async def complete(self,messages,key):
                    self_messages.append(messages)
                    return next(outputs),{}
            self_messages=[]
            def synth(cmd,**kw):
                job=cmd[cmd.index('--project')+1]
                (workspace/job/'prepared.json').write_text(json.dumps({'audio':'gen-test','duration':4,'subtitles':[]}))
            timing=root/'timing.json';timing.write_text(json.dumps({'0':{'evidence_ready_at':10.5,'considered_at':11,'understood_at':11.5,'speak_at':12.3,'reason':'wait for the meaning'}}))
            args=SimpleNamespace(viewing=view,output=root/'final',home=root,persona=root/'persona',studio_config=cfg,studio_backend=root,audio_python='python',reference='ref',timing_plan=timing)
            with patch('reaction_dub.generator.load_context',return_value=([{'content':'persona and memory'}],{'enabled':True,'prefix':'kept'},'private')),patch('reaction_dub.Reactor',return_value=Engine()),patch('reaction_dub.subprocess.run',side_effect=synth):
                await main(args)
            result=json.loads((args.output/'viewing-state.json').read_text())
            self.assertEqual((result['pauses'][0]['duration'],result['events'][1]['output_at']),(4,24))
            self.assertEqual(result['events'][0]['output_at'],12.3)
            self.assertEqual(result['performances'][0]['wall'],12.3)
            self.assertEqual(result['pauses'][0]['source'],12.3)
            self.assertEqual(result['events'][0]['text'],'my words')
            self.assertEqual((view/'viewing-state.json').read_text(),data)
            self.assertFalse(any(e.get('duration_estimated') for e in result['events']))
            self.assertTrue(all(m[-1]['reasoning_content']=='kept' for m in self_messages))
            self.assertTrue(all('source_seconds' in m[1]['content'] for m in self_messages))

if __name__=='__main__':unittest.main()
