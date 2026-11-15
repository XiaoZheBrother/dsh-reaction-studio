"""Isolated, causal pyannote + WhisperX hearing experiment. No DSH writes/TTS.

Uses the baseline ASR text for a controlled comparison. Every inference sees only
audio available at that checkpoint, never the complete episode in advance.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from reaction_audio_evidence import align_cue, reconcile_ids


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def prepare(args):
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    import numpy as np
    import torch
    import imageio_ffmpeg
    from whisperx.alignment import load_align_model, align
    torch.set_num_threads(args.threads)
    baseline = json.loads(args.baseline.read_text('utf-8'))
    if Path(baseline['source']).resolve() != args.video.resolve():
        raise ValueError('Baseline transcript belongs to another video')
    cues = [c for c in baseline['cues'] if c['available_at'] <= args.seconds and c['end'] <= args.seconds]
    if not cues:
        raise ValueError('No baseline ASR cues within requested interval')
    args.output.mkdir(parents=True, exist_ok=True)
    args.models.mkdir(parents=True, exist_ok=True)
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(args.video),
                          '-t', str(args.seconds), '-ac', '1', '-ar', '16000', '-f', 'f32le', 'pipe:1'],
                         capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32).copy()
    model, metadata = load_align_model(language_code=args.language, device='cpu', model_dir=str(args.models/'alignment'))
    pipeline = None
    if not args.alignment_only and args.diarizer == 'pyannote':
        from pyannote.audio import Pipeline
        token = args.token_file.read_text('utf-8-sig').strip() if args.token_file else None
        pipeline = Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=token,
                                           cache_dir=str(args.models/'pyannote'))
        if pipeline is None:
            raise RuntimeError('Community-1 could not be loaded; verify model access before running the comparison')
        pipeline.to(torch.device('cpu'))
    elif not args.alignment_only:
        if args.speakerlab is None:
            raise ValueError('--speakerlab must point to the official 3D-Speaker checkout')
        sys.path.insert(0, str(args.speakerlab.resolve()))
        from speakerlab.bin.infer_diarization import Diarization3Dspeaker
        pipeline = Diarization3Dspeaker(device='cpu', include_overlap=False,
                                       model_cache_dir=str(args.models/'3d-speaker'))
    signature = hashlib.sha256(json.dumps({
        'baseline': hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        'audio': hashlib.sha256(raw).hexdigest(), 'seconds': args.seconds,
        'language': args.language, 'alignment_only': args.alignment_only,
        'diarizer': args.diarizer,
        'implementation': hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name('reaction_audio_evidence.py').read_bytes()).hexdigest(),
    }, sort_keys=True).encode()).hexdigest()
    state = {'source': str(args.video), 'seconds': args.seconds, 'complete': False,
             'backend': 'WhisperX forced alignment' + (' (no diarization)' if args.alignment_only else ' + '+args.diarizer),
             'overlap_detection': args.diarizer == 'pyannote' and not args.alignment_only,
             'baseline_sha256': hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
             'input_signature': signature,
             'policy': 'past_audio_only_immutable_released_cues', 'cues': [], 'checkpoints': []}
    history, next_id, previous = [], 0, 0
    for cursor in sorted({c['available_at'] for c in cues}):
        snapshot = args.output/f'hearing-{cursor:07.2f}.json'
        if snapshot.exists():
            state = json.loads(snapshot.read_text('utf-8'))
            if state.get('input_signature') != signature:
                raise ValueError('Checkpoint inputs differ; choose a new output directory')
            history, next_id, previous = state['cues'], state['next_voice_id'], cursor
            continue
        past = samples[:int(cursor*16000)]
        turns = []
        if pipeline is not None:
            if args.diarizer == 'pyannote':
                result = pipeline({'waveform': torch.from_numpy(past.copy()).unsqueeze(0), 'sample_rate': 16000})
                turns = [{'start': t.start, 'end': min(cursor, t.end), 'speaker_id': speaker}
                         for t, _, speaker in result.speaker_diarization.itertracks(yield_label=True)]
            else:
                result = pipeline(past.copy(), wav_fs=16000)
                turns = [{'start': float(a), 'end': min(cursor,float(b)), 'speaker_id': str(s)} for a,b,s in result]
            turns, next_id = reconcile_ids(turns, history, previous, next_id)
        current = [c for c in cues if c['available_at'] == cursor]
        added = []
        for cue in current:
            aligned = align([{'start': cue['start'], 'end': cue['end'], 'text': cue['text']}],
                            model, metadata, past, 'cpu', return_char_alignments=False, print_progress=False,
                            interpolate_method='ignore')
            added.extend(align_cue(cue, aligned.get('word_segments', []), turns, cursor))
        if args.diarizer == 'campplus':
            for cue in added:
                cue['limitations'].append('This backend does not detect simultaneous speakers; a single label cannot prove only one voice was present.')
        state['cues'].extend(added)
        state['checkpoints'].append({'available_at': cursor, 'audio_visible_until': cursor, 'turns': turns,
                                     'new_cues': len(added)})
        state.update(processed_until=cursor, next_voice_id=next_id)
        save(snapshot, state)
        save(args.output/'hearing.json', state)
        history, previous = list(state['cues']), cursor
        print(json.dumps({'heard_until': cursor, 'cues': len(state['cues']), 'voices': next_id}), flush=True)
    state['complete'] = True
    save(args.output/'hearing.json', state)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--models', type=Path, required=True)
    p.add_argument('--token-file', type=Path)
    p.add_argument('--seconds', type=float, default=180)
    p.add_argument('--language', default='ja')
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--alignment-only', action='store_true')
    p.add_argument('--diarizer', choices=['pyannote','campplus'], default='pyannote')
    p.add_argument('--speakerlab', type=Path)
    prepare(p.parse_args())
