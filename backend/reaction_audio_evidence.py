"""Conservative timestamp attribution. Voice identities are never character names."""
import math
import unicodedata
from numbers import Real


def overlap(a, b, c, d):
    return max(0.0, min(b, d) - max(a, c))


def speaker_for_interval(start, end, turns):
    """Regular (not exclusive) turns preserve simultaneous voices as uncertainty."""
    scores = {}
    for t in turns:
        amount = overlap(start, end, t['start'], t['end'])
        if amount:
            scores[t['speaker_id']] = scores.get(t['speaker_id'], 0) + amount
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    duration = max(end-start, 1e-9)
    candidates = [{'speaker_id': k, 'overlap_fraction': min(1, v/duration)} for k, v in ranked]
    # Evidence thresholds, not speech frequency or model confidence probabilities.
    accepted = bool(ranked and ranked[0][1]/duration >= .6 and
                    (len(ranked) == 1 or ranked[1][1]/duration <= .2))
    return (ranked[0][0] if accepted else None), candidates


def reconcile_ids(turns, history, available_before, next_id):
    """Map rerun cluster labels using only immutable, already released intervals.

    Ambiguous splits/merges receive fresh IDs; do not rewrite old cues using future
    audio. Identity continuity remains a hypothesis, never a confirmed character.
    """
    scores = {}
    for turn in turns:
        for old in history:
            if old['available_at'] > available_before or not old.get('speaker_id'):
                continue
            amount = overlap(turn['start'], turn['end'], old['start'], old['end'])
            key = (turn['speaker_id'], old['speaker_id'])
            scores[key] = scores.get(key, 0) + amount
    mapping = {}
    for local in sorted({t['speaker_id'] for t in turns}):
        options = sorted([(v, old) for (new, old), v in scores.items() if new == local and v > 0], reverse=True)
        if options and options[0][0] >= .5 and (len(options) == 1 or options[0][0] >= 2*options[1][0]):
            old = options[0][1]
            rivals = sorted([v for (new, other), v in scores.items() if other == old and new != local], reverse=True)
            if not rivals or options[0][0] >= 2*rivals[0]:
                mapping[local] = old
        if local not in mapping:
            next_id += 1
            mapping[local] = f'voice_{next_id:03d}'
    return [{**t, 'speaker_id': mapping[t['speaker_id']]} for t in turns], next_id


def align_cue(original, words, turns, available_at):
    """Split text at measured speaker changes. Missing alignments stay unknown."""
    output = []
    for i, word in enumerate(words):
        text = word.get('word', word.get('text', ''))
        if not text:
            continue
        start, end = word.get('start'), word.get('end')
        valid = (isinstance(start, Real) and isinstance(end, Real)
                 and not isinstance(start, bool) and not isinstance(end, bool)
                 and math.isfinite(start) and math.isfinite(end)
                 and 0 <= start < end <= available_at)
        if valid:
            start, end = float(start), float(end)
            speaker, candidates = speaker_for_interval(start, end, turns)
        else:
            start, end, speaker, candidates = original['start'], original['end'], None, []
        row = {'start': start, 'end': end, 'text': text, 'speaker_id': speaker,
               'alignment': 'forced_aligned' if valid else 'unresolved', 'score': word.get('score'),
               'speaker_candidates': candidates}
        if output and output[-1]['alignment'] == row['alignment'] and output[-1]['speaker_id'] == speaker:
            output[-1]['end'] = max(output[-1]['end'], end)
            output[-1]['text'] += text
            output[-1]['words'].append(row)
        else:
            output.append({**row, 'words': [row]})
    def compact(text):
        return ''.join(unicodedata.normalize('NFC', text).split())
    if not output or compact(''.join(r['text'] for r in output)) != compact(original['text']):
        output = [{'start': original['start'], 'end': original['end'], 'text': original['text'],
                   'speaker_id': None, 'alignment': 'unresolved', 'words': []}]
    if len(output) == 1:
        output[0]['text'] = original['text']
    for i, row in enumerate(output):
        row.update(id=f"{original['id']}-aligned-{i}", parent_cue_id=original['id'],
                   original_text=original['text'],
                   available_at=available_at, character=None, language=original.get('language', 'ja'),
                   speaker_confidence={'label': 'acoustic_candidate' if row['speaker_id'] else 'unknown', 'calibrated': False},
                   limitations=['Voice cluster does not identify a character or distinguish inner monologue from spoken dialogue.',
                                'Forced alignment cannot verify whether the ASR text is correct.'])
    return output


def recent_heard(cues, count=8):
    """Keep recent source utterances rather than truncating at speaker splits."""
    selected, parents = [], set()
    for cue in reversed(cues):
        parent = cue.get('parent_cue_id', cue['id'])
        if parent not in parents and len(parents) >= count:
            break
        parents.add(parent)
        selected.append(cue)
    return list(reversed(selected))


def compact_hearing(cues):
    """Inject shared backend caveats once while retaining every selected cue."""
    keys = ('id', 'start', 'end', 'text', 'speaker_id', 'speaker_confidence',
            'asr_avg_logprob', 'parent_cue_id', 'alignment')
    return {'heard_dialogue': [{k: c[k] for k in keys if k in c} for c in cues],
            'hearing_limitations': list(dict.fromkeys(s for c in cues for s in c.get('limitations', [])))}


def narrative_state(understanding):
    """Utterance revisions already have a dedicated ledger; do not inject twice."""
    return {k: v for k, v in understanding.items() if k != 'speech_updates'}
