"""Reproducible local-video evaluation; never streams or writes character memory.

Calls real providers. Run explicitly, not in the unit test suite.
Each request sees only frames at or before its playback cursor.
"""
import argparse
import asyncio
import base64
import json
import subprocess
import uuid
from pathlib import Path
from reaction_server import Reactor, validate_input


async def replay(args):
    import imageio_ffmpeg
    args.output.mkdir(parents=True, exist_ok=False)
    frames_dir = args.output/'frames'
    frames_dir.mkdir()
    (args.output/'metadata.json').write_text(json.dumps({'mode':'offline-proposals-no-tts',
        'seconds':args.seconds,'step':args.step,'realAudioPlayback':False,
        'note':'Only perception and proposed reactions are evaluated; no speech playback or queue simulation.'},indent=2),encoding='utf-8')
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v','error','-i',str(args.video),
                    '-t',str(args.seconds+1),'-vf','fps=1,scale=768:-2','-q:v','3',
                    '-start_number','0',str(frames_dir/'%05d.jpg')],check=True)
    reactor = Reactor(args.home,args.persona)
    timeline = str(uuid.uuid4())
    results=[]
    for cursor in range(args.step,args.seconds+1,args.step):
        # fps filter samples frame centres; label conservatively at end of second.
        begin = cursor-args.step
        count = min(8,args.step)
        samples = [begin + round(i*(args.step-1)/max(1,count-1)) for i in range(count)]
        frames=[{'at':at+1,'image':'data:image/jpeg;base64,'+base64.b64encode((frames_dir/f'{at:05d}.jpg').read_bytes()).decode()} for at in samples]
        try:
            result = await reactor.observe(validate_input({'timeline':timeline,'cursor':cursor,'frames':frames,
                                                           'playback':{'spoken':[], 'busy':False}}))
        except Exception as exc:
            result={'cursor':cursor,'error':str(exc),'story':dict(reactor.story)}
        results.append(result)
        (args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:result.get(key) for key in ('cursor','action','text','elapsed','timings','error')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--persona',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=200)
    parser.add_argument('--step',type=int,default=10)
    args=parser.parse_args()
    if not 1 <= args.step <= 30 or not args.step <= args.seconds <= 300:
        parser.error('step must be 1–30; seconds must be step–300')
    asyncio.run(replay(args))
