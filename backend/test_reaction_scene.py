import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from live_pilot_chat import generator

class SceneContextTests(unittest.TestCase):
    def test_reaction_keeps_persona_memory_prefix_but_excludes_writing_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            for name in ['bili-duty','feiyu-runtime/writing/self','soul-md/memory/fish/topics']:(home/name).mkdir(parents=True,exist_ok=True)
            (home/'persona.md').write_text('identity-original',encoding='utf-8')
            (home/'feiyu-runtime/config.json').write_text(json.dumps({'memoryName':'fish'}),encoding='utf-8')
            (home/'soul-md/memory/fish/topics/life.md').write_text('memory-original',encoding='utf-8')
            (home/'bili-duty/comment-prefill.json').write_text(json.dumps({'enabled':True,'prefix':'original-prefix'}),encoding='utf-8')
            (home/'feiyu-runtime/writing/self/example.json').write_text(json.dumps({'text':'WRITING-ONLY'}),encoding='utf-8')
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'test-key'}):
                for scene in ['reaction','reaction_offline']:
                    messages,prefix,_=generator.load_context(home,home/'persona.md',scene=scene)
                    self.assertIn('identity-original',messages[0]['content'])
                    self.assertIn('memory-original',messages[0]['content'])
                    self.assertNotIn('WRITING-ONLY',messages[0]['content'])
                    self.assertEqual(prefix,{'enabled':True,'prefix':'original-prefix'})
                messages,_,_=generator.load_context(home,home/'persona.md')
                self.assertIn('WRITING-ONLY',messages[0]['content'])

if __name__=='__main__':unittest.main()
