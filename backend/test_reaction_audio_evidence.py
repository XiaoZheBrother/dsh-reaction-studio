import unittest
from reaction_audio_evidence import align_cue, reconcile_ids, speaker_for_interval, recent_heard, compact_hearing, narrative_state


class AudioEvidenceTests(unittest.TestCase):
    def test_overlap_does_not_force_a_speaker(self):
        turns = [{'start': 0, 'end': 2, 'speaker_id': x} for x in ('a', 'b')]
        self.assertIsNone(speaker_for_interval(0, 1, turns)[0])

    def test_words_split_at_speaker_change(self):
        cue = {'id': 'a', 'start': 0, 'end': 2, 'text': '你好'}
        rows = align_cue(cue, [{'word': '你', 'start': 0, 'end': 1}, {'word': '好', 'start': 1, 'end': 2}],
                         [{'start': 0, 'end': 1, 'speaker_id': 'a'}, {'start': 1, 'end': 2, 'speaker_id': 'b'}], 2)
        self.assertEqual([r['speaker_id'] for r in rows], ['a', 'b'])
        self.assertTrue(all(r['character'] is None for r in rows))

    def test_missing_or_future_alignment_stays_unknown(self):
        cue = {'id': 'a', 'start': 0, 'end': 2, 'text': '你好'}
        for words in ([], [{'word': '你'}], [{'word': '你', 'start': 1, 'end': 10}]):
            row = align_cue(cue, words, [{'start': 0, 'end': 20, 'speaker_id': 'a'}], 2)[0]
            self.assertIsNone(row['speaker_id'])
            self.assertEqual(row['alignment'], 'unresolved')

    def test_relabel_uses_past_only_without_mutation(self):
        old = [{'start': 0, 'end': 2, 'speaker_id': 'voice_001', 'available_at': 2},
               {'start': 2, 'end': 4, 'speaker_id': 'future', 'available_at': 4}]
        turns = [{'start': 0, 'end': 4, 'speaker_id': 'new'}]
        result, count = reconcile_ids(turns, old, 2, 1)
        self.assertEqual(result[0]['speaker_id'], 'voice_001')
        self.assertEqual(turns[0]['speaker_id'], 'new')
        self.assertEqual(count, 1)

    def test_ambiguous_merge_does_not_claim_identity(self):
        old = [{'start': i, 'end': i+1, 'speaker_id': str(i), 'available_at': 2} for i in range(2)]
        result, _ = reconcile_ids([{'start': 0, 'end': 2, 'speaker_id': 'x'}], old, 2, 2)
        self.assertEqual(result[0]['speaker_id'], 'voice_003')

    def test_alignment_cannot_silently_drop_transcript(self):
        cue = {'id': 'a', 'start': 0, 'end': 2, 'text': '你好'}
        row = align_cue(cue, [{'word': '你', 'start': 0, 'end': 1}], [], 2)[0]
        self.assertEqual(row['text'], '你好')
        self.assertEqual(row['alignment'], 'unresolved')

    def test_recent_context_keeps_source_utterances(self):
        cues = [{'id': str(i), 'parent_cue_id': str(i//3)} for i in range(9)]
        self.assertEqual(recent_heard(cues, 2), cues[3:])

    def test_numeric_subclasses_from_alignment_are_accepted(self):
        class Scalar(float):
            pass
        cue = {'id': 'a', 'start': 0, 'end': 2, 'text': '好'}
        row = align_cue(cue, [{'word': '好', 'start': Scalar(.1), 'end': Scalar(1)}], [], 2)[0]
        self.assertEqual(row['alignment'], 'forced_aligned')

    def test_original_spaces_are_retained(self):
        cue = {'id': 'a', 'start': 0, 'end': 2, 'text': '你 好'}
        row = align_cue(cue, [{'word': '你', 'start': 0, 'end': 1}, {'word': '好', 'start': 1, 'end': 2}], [], 2)[0]
        self.assertEqual(row['text'], cue['text'])
        self.assertEqual(row['original_text'], cue['text'])

    def test_shared_caveats_are_injected_once_without_losing_cues(self):
        cues = [{'id': str(i), 'text': 'hi', 'speaker_id': None, 'limitations': ['uncertain']} for i in range(9)]
        result = compact_hearing(cues)
        self.assertEqual(len(result['heard_dialogue']), 9)
        self.assertEqual(result['hearing_limitations'], ['uncertain'])
        self.assertEqual(cues[0]['limitations'], ['uncertain'])

    def test_narrative_projection_preserves_raw_revision_record(self):
        source = {'story': 'story', 'cast': [], 'speech_updates': [{'id': 'x'}]}
        self.assertEqual(narrative_state(source), {'story': 'story', 'cast': []})
        self.assertEqual(source['speech_updates'], [{'id': 'x'}])


if __name__ == '__main__':
    unittest.main()
