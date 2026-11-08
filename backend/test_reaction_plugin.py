import unittest
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock
from plugin_rpc import dispatch

class PluginTests(unittest.TestCase):
    def test_independent_worker_restores_shared_dependency_without_parent_env(self):
        import live_performance
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'job.json'
            path.write_text(json.dumps({'live_backend':str(Path(live_performance.__file__).parent)}))
            env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('reaction_produce.py')),'--job',str(path),'--help'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_dispatch_does_not_allow_arbitrary_method(self):
        with self.assertRaises(ValueError): dispatch(Mock(),'__dict__',{})
    def test_start_preserves_duration_and_afterword(self):
        jobs=Mock();dispatch(jobs,'start',{'material_id':'episode','job_id':'one','seconds':180,'afterword':False})
        jobs.start.assert_called_once_with('episode','one',180,False)
    def test_pause_and_replay_are_requests_not_direct_edits(self):
        jobs=Mock();dispatch(jobs,'pause_analysis',{'job_id':'one','topic':'why'})
        jobs.control.assert_called_once_with('one','pause_analysis','why')
        jobs.reset_mock();dispatch(jobs,'replay',{'job_id':'one'})
        jobs.control.assert_called_once_with('one','replay',seconds=5)
