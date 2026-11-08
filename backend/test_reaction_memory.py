import unittest
from reaction_memory import StoryMemory


class StoryMemoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = StoryMemory(recent_count=2, episode_size=2)
        self.facts = dict.fromkeys(('visual','dialogue','event','correction'),'evidence')

    def add(self, count):
        for i in range(count): self.memory.record(i*8, self.facts, [i*8])

    def test_recent_observations_not_compressed_early(self):
        self.add(3)
        self.assertEqual(self.memory.pending_episode(),[])
        self.assertEqual(len(self.memory.snapshot()['recent']),3)

    def test_archive_preserves_originals_and_recent_detail(self):
        self.add(4)
        pending = self.memory.pending_episode()
        self.memory.archive([o['id'] for o in pending],'earlier cause')
        self.assertEqual(len(self.memory.observations),4)
        self.assertEqual([o['id'] for o in self.memory.snapshot()['recent']],['o3','o4'])
        self.assertEqual(self.memory.snapshot()['episodes'][0]['summary'],'earlier cause')

    def test_later_episode_does_not_overwrite_earlier_cause(self):
        self.add(4)
        self.memory.archive(['o1','o2'],'cause')
        self.add(2)
        self.memory.archive(['o3','o4'],'new event')
        self.assertEqual([e['summary'] for e in self.memory.episodes],['cause','new event'])

    def test_invalid_archive_keeps_complete_pending_segment(self):
        self.add(4)
        for ids, summary in [(['o99'],'wrong'), (['o1','o2'],'x'*501), (['o1','o2'],'')]:
            with self.assertRaises(ValueError): self.memory.archive(ids,summary)
        self.assertEqual(self.memory.archived,0)
        self.assertEqual(len(self.memory.snapshot()['recent']),4)

    def test_observations_and_snapshots_are_copies(self):
        self.add(4)
        self.facts['visual']='mutated'
        self.memory.snapshot()['recent'][0]['visual']='mutated'
        self.memory.pending_episode()[0]['visual']='mutated'
        self.assertEqual(self.memory.observations[0]['visual'],'evidence')


if __name__ == '__main__': unittest.main()
