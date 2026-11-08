import json
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from pathlib import Path
from reaction_episode import frame_batch, performance, save, nonempty_response
from reaction_intent import parse_intent


class EpisodeProductionTests(unittest.TestCase):
    def test_inactive_replay_field_does_not_reject_silence(self):
        result=parse_intent('{"action":"continue","focus_at":null,"seconds":null}',0,1372)
        self.assertEqual(result['action'],'continue')
        with self.assertRaises(ValueError):
            parse_intent('{"action":"replay","focus_at":1372,"seconds":null}',0,1372)

    def test_observation_never_exceeds_seen_time_or_episode_end(self):
        for cursor in (.1,2,123.12,1419.9,1420):
            for rewind in (0,1,10):
                batch=frame_batch(cursor,1420,rewind)
                self.assertLessEqual(len(batch),8)
                self.assertTrue(all(0<=at<=cursor and at<1420 for _,at in batch))
                self.assertEqual(batch,sorted(set(batch)))

    def test_checkpoint_replaces_complete_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            save(path,{'cursor':2,'text':'原始记录'})
            save(path,{'cursor':4,'text':'保留之前理解'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['cursor'],4)
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_duration_normalization_does_not_change_selected_action(self):
        result=performance({'performance':{'expression':'屑屑眼','motion':'tilt_left','duration':0}})
        self.assertEqual((result['expression'],result['motion'],result['duration']),('屑屑眼','tilt_left',1))
        with self.assertRaises(ValueError):
            performance({'performance':{'motion':'invented'}})

    def test_checkpoint_survives_transient_windows_reader_lock(self):
        original=Path.replace;attempts=[]
        def replace(path,target):
            attempts.append(target)
            if len(attempts)==1:raise PermissionError('reader still has old file open')
            return original(path,target)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';save(path,{'cursor':2})
            with patch.object(Path,'replace',new=replace),patch('reaction_episode.time.sleep'):
                save(path,{'cursor':4})
            self.assertEqual(json.loads(path.read_text())['cursor'],4)
            self.assertEqual(len(attempts),2)
            self.assertFalse(path.with_suffix('.tmp').exists())


class EmptyResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_content_retries_without_replacing_actor_words(self):
        request = AsyncMock(side_effect=['', '  ', '她自己选择的话'])
        with patch('reaction_episode.asyncio.sleep', new_callable=AsyncMock):
            self.assertEqual(await nonempty_response(request), '她自己选择的话')
        self.assertEqual(request.await_count, 3)

    async def test_persistent_empty_response_stops_instead_of_inventing_speech(self):
        request = AsyncMock(return_value='')
        with patch('reaction_episode.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaisesRegex(ValueError, 'empty content'):
                await nonempty_response(request)
        self.assertEqual(request.await_count, 3)


if __name__=='__main__':unittest.main()
