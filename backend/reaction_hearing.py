"""Local timestamped ASR and causal anonymous voice matching.

Models live in an isolated environment. Scores are not calibrated probabilities;
voice matching is a candidate cue, never a character-name classifier.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path


def prepare(video, seconds, output, model_dir):
    import numpy as np
    import torch
    import imageio_ffmpeg
    from faster_whisper import WhisperModel
    from huggingface_hub import snapshot_download
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    torch.set_num_threads(4)
    output.parent.mkdir(parents=True, exist_ok=True)
    wav = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v','error','-i',str(video),'-t',str(seconds),
                          '-f','f32le','-ac','1','-ar','16000','pipe:1'],capture_output=True,check=True).stdout
    samples = np.frombuffer(wav, dtype=np.float32)
    asr = WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4,download_root=str(model_dir/'whisper'))
    speaker_dir = model_dir/'ecapa'
    snapshot_download('speechbrain/spkrec-ecapa-voxceleb',local_dir=speaker_dir,
                      allow_patterns=['*.ckpt','*.yaml','*.txt'])
    voice = EncoderClassifier.from_hparams(source=str(speaker_dir),savedir=str(speaker_dir),run_opts={'device':'cpu'},local_strategy=LocalStrategy.COPY)
    cues=[];centroids=[]
    # ASR chunks constrain context. Evidence is released only at chunk end;
    # future chunks never influence voice labels or previously emitted cues.
    for start in range(0,math.ceil(seconds),12):
        end = min(seconds,start+12)
        chunk=samples[int(start*16000):int(end*16000)]
        segments,_=asr.transcribe(chunk,language='ja',beam_size=5,word_timestamps=True,
            vad_filter=True,condition_on_previous_text=False)
        for seg in segments:
            if not seg.text.strip():continue
            a=max(start,start+seg.start);b=min(end,start+seg.end)
            sound=samples[int(a*16000):int(b*16000)]
            speaker=None;similarity=None;margin=None;quality='unknown'
            if len(sound)>=16000 and seg.no_speech_prob<.6:
                with torch.no_grad():
                    emb=voice.encode_batch(torch.from_numpy(sound.copy()).unsqueeze(0)).flatten().numpy()
                emb=emb/max(np.linalg.norm(emb),1e-9)
                sims=sorted([(float(np.dot(emb,c)),i) for i,c in enumerate(centroids)],reverse=True)
                similarity=sims[0][0] if sims else None
                margin=sims[0][0]-sims[1][0] if len(sims)>1 else None
                # Thresholds apply only to acoustic uncertainty, not speaking frequency.
                if not sims or similarity<.55:
                    centroids.append(emb);speaker=f'voice_{len(centroids):02d}';quality='new_unverified_voice'
                elif similarity>=.72 and (margin is None or margin>=.08):
                    speaker=f'voice_{sims[0][1]+1:02d}';quality='candidate_match'
                else:quality='ambiguous_voice'
            cues.append({'id':f'audio-{len(cues):04d}','start':round(a,3),'end':round(b,3),'available_at':end,
                'text':seg.text.strip(),'language':'ja','speaker_id':speaker,'character':None,
                'asr_avg_logprob':seg.avg_logprob,'no_speech_probability':seg.no_speech_prob,
                'speaker_confidence':{'label':quality,'cosine_similarity':similarity,'margin':margin,'calibrated':False},
                'words':[{'start':round(start+w.start,3),'end':round(min(end,start+w.end),3),'text':w.word,'probability':w.probability} for w in seg.words or []],
                'limitations':['May mix voices within one ASR segment; music and acted voices affect matching.','Anonymous voice candidate does not identify a character.']})
        result={'source':str(video.resolve()),'seconds':seconds,'processed_until':end,'complete':end==seconds,
                'backend':'faster-whisper-small + speechbrain-ecapa-voxceleb','cues':cues}
        tmp=output.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(output)
        print(json.dumps({'heard_until':end,'cues':len(cues),'voice_candidates':len(centroids)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--video',type=Path,required=True);p.add_argument('--seconds',type=float,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--models',type=Path,required=True)
    a=p.parse_args();prepare(a.video,a.seconds,a.output,a.models)
