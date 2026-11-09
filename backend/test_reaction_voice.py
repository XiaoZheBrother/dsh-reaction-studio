import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from reaction_voice import load_voice,identity
from reaction_onset import choose_onset
import test_reaction_mcp as support

class VoiceTests(unittest.IsolatedAsyncioTestCase):
    def test_presets_reject_invalid_vectors(self):
        for vector in ([0]*7,[float('nan')]*8,[True]*8):
            with self.assertRaises(ValueError):load_voice({'profile':{'engine':'IndexTTS2','presets':[{'id':'b','emotion_vector':vector}]}})

    async def test_onset_rejects_future_and_instant_response(self):
        event={'cursor':10,'frames':[10.25]}
        async def ask(*args):raise AssertionError('Future evidence reached actor')
        with self.assertRaises(ValueError):await choose_onset(event,{'input':{'seconds':20}},'.',ask,0,[])
        event['frames']=[]
        async def select(prompt,context,parser):
            self.assertNotIn('future_plot',context)
            with self.assertRaises(ValueError):parser(json.dumps({'choice':'speak','understood_at':10,'speak_at':10,'reason':'instant'}))
            with self.assertRaises(ValueError):parser(json.dumps({'choice':'speak','understood_at':10.1,'speak_at':11,'reason':'overlap'}))
            return parser('{"choice":"defer","reason":"want to keep watching"}')
        result=await choose_onset(event,{'input':{'seconds':20},'future_plot':'secret'},'.',select,12,[])
        self.assertEqual(result['choice'],'defer')

    async def test_onset_only_gets_hearing_released_by_cursor(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'hearing.json'
            path.write_text(json.dumps({'cues':[{'id':'heard','end':8,'available_at':9},{'id':'later','end':9,'available_at':12}]}))
            async def ask(prompt,context,parser):
                self.assertEqual([c['id'] for c in context['evidence']['timestamped_hearing']],['heard'])
                return parser('{"choice":"speak","understood_at":10.2,"speak_at":10.6,"reason":"my opening"}')
            result=await choose_onset({'cursor':10},{'input':{'seconds':20,'hearing':str(path)}},t,ask,0,[])
            self.assertEqual(result['speak_at'],10.6)

class SnapshotTests(unittest.TestCase):
    setUp=support.JobTests.setUp
    tearDown=support.JobTests.tearDown
    @patch('reaction_mcp.subprocess.Popen')
    def test_new_voice_is_snapshotted_and_old_job_is_unchanged(self,spawn):
        spawn.return_value.pid=123
        self.jobs.start('episode','old',3,False)
        old=self.jobs.folder('old')/'job.json';before=old.read_bytes()
        cfg=self.root/'voice.json';ref=self.root/'ref.wav';ref.write_bytes(b'confirmed')
        cfg.write_text(json.dumps({'assets':{'voice-reference':{'path':str(ref)}}}))
        profile={'id':'B','engine':'IndexTTS2','presets':[{'id':'1','emotion_vector':[0]*8}]}
        self.jobs.config['voice_studio']={'config':str(cfg),'profile':profile}
        self.jobs.start('episode','old',3,False)
        self.assertEqual(old.read_bytes(),before)
        (old.parent/'production.json').write_text('{"phase":"complete"}')
        self.jobs.start('episode','new',3,False)
        saved=json.loads((self.jobs.folder('new')/'job.json').read_text('utf-8'))['voice_studio']
        self.assertEqual(saved['profile'],profile)
        self.assertEqual(len(saved['reference_sha256']),64)
        cfg.write_text('{}')
        self.assertIn('assets',saved['config_snapshot'])

if __name__=='__main__':unittest.main()
