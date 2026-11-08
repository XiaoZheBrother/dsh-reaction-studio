import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from reaction_mcp import ReactionJobs
from reaction_job_control import exclusive_job, pending_control


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config={'job_root':str(self.root/'jobs'),'home':str(self.root/'home'),'persona':str(self.root/'soul'),
            'python':'python','chromium':'chrome','materials':{'episode':{'path':'approved.mp4','seconds':1420,'title':'episode'}}}
        p=self.root/'config.json';p.write_text(json.dumps(self.config));self.jobs=ReactionJobs(p)
    def tearDown(self):self.tmp.cleanup()

    def test_agent_cannot_supply_paths_or_exceed_trim(self):
        for job in ('../escape','C:\\file','a/b',''):
            with self.assertRaises(ValueError):self.jobs.folder(job)
        with self.assertRaises(ValueError):self.jobs.start('unapproved','test')
        with self.assertRaises(ValueError):self.jobs.start('episode','test',1421)

    @patch('reaction_mcp.subprocess.Popen')
    def test_retry_and_competing_jobs_do_not_spawn_duplicates(self,spawn):
        spawn.return_value.pid=123
        self.jobs.start('episode','one',3,False)
        self.jobs.start('episode','one',3,False)
        self.assertEqual(spawn.call_count,1)
        with self.assertRaises(ValueError):self.jobs.start('episode','two',3,False)
        with self.assertRaises(ValueError):self.jobs.start('episode','one',4,False)

    @patch('reaction_mcp.subprocess.Popen')
    def test_control_ack_is_not_execution_and_applied_once(self,spawn):
        spawn.return_value.pid=123;self.jobs.start('episode','one',3,False)
        receipt=self.jobs.control('one','pause_analysis','这个疑问')
        self.assertTrue(receipt['queued']);self.assertEqual(self.jobs.status('one')['controls'],[])
        output=self.jobs.folder('one')/'viewing';state={'events':[]}
        request=pending_control(output,state);self.assertEqual(request['id'],receipt['control_id'])
        state['events'].append({'control_id':request['id']})
        self.assertIsNone(pending_control(output,state))

    @patch('reaction_mcp.subprocess.Popen')
    def test_running_owner_and_completed_job_survive_client_restart(self,spawn):
        spawn.return_value.pid=123;self.jobs.start('episode','one',3,False)
        folder=self.jobs.folder('one')
        with exclusive_job(folder/'.production.lock'):
            (folder/'launch.json').write_text('{"at":0}')
            self.assertTrue(self.jobs.status('one')['running'])
        (folder/'production.json').write_text('{"phase":"complete","video":"result.mp4"}')
        self.jobs.start('episode','one',3,False)
        self.assertEqual(spawn.call_count,1)
        with self.assertRaises(ValueError):self.jobs.control('one','replay')

    @patch('reaction_mcp.subprocess.Popen')
    def test_new_hearing_configuration_does_not_rewrite_old_job(self,spawn):
        spawn.return_value.pid=123
        self.jobs.start('episode','one',3,False)
        path=self.jobs.folder('one')/'job.json';original=path.read_bytes()
        self.jobs.config.update(hearing_python='new-hearing-python',hearing_models='models')
        self.jobs.start('episode','one',3,False)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(spawn.call_count,1)


if __name__=='__main__':unittest.main()
