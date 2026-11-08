"""Offline fixed-step rendering: wall-clock speed cannot drop output frames."""
import array,asyncio,base64,json,math,re,subprocess,time
from pathlib import Path
from reaction_pacing import PlaybackTimeline, source_audio

def pcm_audio(ff,path):
    raw=subprocess.run([ff,'-v','error','-i',str(path),'-f','s16le','-ac','1','-ar','8000','pipe:1'],capture_output=True,check=True).stdout
    samples=array.array('h');samples.frombytes(raw);return samples

async def render_frames(page,args,replay,performances,ff):
    if getattr(args,'follow',False):
        return await render_following(page,args,replay,performances,ff)
    pauses=json.loads((args.timeline or args.replay/'clock-metrics.json').read_text(encoding='utf-8')).get('pauses',[])
    timeline=PlaybackTimeline(pauses)
    fps=24;frames=args.output/'source-frames';frames.mkdir()
    subprocess.run([ff,'-v','error','-y','-ss',str(args.start),'-i',str(args.video),'-t',str(args.seconds),'-vf',f'fps={fps},scale=996:560','-q:v','2',str(frames/'%06d.jpg')],check=True)
    count=len(list(frames.glob('*.jpg')));voices=[]
    for event in replay:
        path=args.replay/Path(event['audio']).name;samples=pcm_audio(ff,path)
        voices.append({**event,'samples':samples,'duration':len(samples)/8000,'path':path})
    duration=max([timeline.output_at(args.seconds)]+[v['at']+v['duration'] for v in voices])+.15
    nframes=math.ceil(duration*fps);duration=nframes/fps
    original=source_audio(ff,args.video,args.output/'original.f32le',args.start,args.seconds,pauses)
    inputs=['-f','f32le','-ar','48000','-ac','2','-i',str(original)];filters=[f'[0:a]apad,atrim=duration={duration}[original]'];mix='[original]'
    for i,v in enumerate(voices,1):
        inputs+=['-i',str(v['path'])];filters.append(f'[{i}:a]volume=1.4,adelay={round(v["at"]*1000)}:all=1[a{i}]');mix+=f'[a{i}]'
    filters.append(mix+f'amix=inputs={len(voices)+1}:duration=first:normalize=0,aresample=48000,alimiter=limit=0.891251:level=0:latency=1[mix]')
    audio=args.output/'mixed.wav'
    subprocess.run([ff,'-v','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[mix]','-c:a','pcm_s16le',str(audio)],check=True)
    out=args.output/'大肥鱼陪看-流畅多行字幕版.mp4'
    encoder=subprocess.Popen([ff,'-v','error','-y','-f','image2pipe','-framerate',str(fps),'-vcodec','mjpeg','-i','pipe:0','-i',str(audio),'-map','0:v','-map','1:a','-c:v','libx264','-threads','2','-preset','fast','-crf','17','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(out)],stdin=subprocess.PIPE)
    started=time.monotonic()
    try:
        for i in range(nframes):
            t=i/fps;active=next((v for v in voices if v['at']<=t<v['at']+v['duration']),None);caption='';mouth=0
            if active:
                vt=t-active['at'];caption=next((c['text'] for c in active['captions'] if c['start']<=vt<=c['end']),'')
                center=int(vt*8000);samples=active['samples'][max(0,center-160):center+160]
                if samples:mouth=min(1,7*math.sqrt(sum((s/32768)**2 for s in samples)/len(samples)))
            source_index=min(count,int(min(timeline.source_at(t),args.seconds)*fps)+1)
            data=await page.evaluate('(a)=>window.offlineFrame(...a)',[t,f'/source-frame/{source_index:06d}.jpg',caption,mouth])
            encoder.stdin.write(base64.b64decode(data.split(',',1)[1]))
            if i%120==0:print(json.dumps({'rendered_seconds':round(t,2),'total_seconds':duration,'frames':i,'wall_seconds':round(time.monotonic()-started,1)}),flush=True)
        encoder.stdin.close();code=encoder.wait()
        if code:raise RuntimeError(f'Frame encoder failed: {code}')
    except BaseException:
        encoder.kill();encoder.wait();raise
    report={'mode':'offline_fixed_step','fps':fps,'frames':nframes,'duration':duration,'pauses':pauses,'source_end':args.seconds,'speech_count':len(voices),'performances':len(performances),'source_audio_gain':1,'speech':[{'id':v['id'],'at':v['at'],'duration':v['duration'],'captions':v['captions']} for v in voices]}
    (args.output/'render-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OFFLINE RENDER COMPLETE',flush=True)


async def render_following(page,args,replay,performances,ff):
    """Render committed observations while the independent watcher continues.

    Frames cannot advance past the checkpoint watermark. Audio is muxed only after
    viewing finishes, so a slow network never drops or shifts rendered frames.
    """
    fps=24;frames=args.output/'source-frames';frames.mkdir(exist_ok=True)
    if len(list(frames.glob('*.jpg')))<math.ceil(args.seconds*fps):
        subprocess.run([ff,'-v','error','-y','-i',str(args.video),'-t',str(args.seconds),'-vf',f'fps={fps},scale=996:560','-q:v','2',str(frames/'%06d.jpg')],check=True)
    count=len(list(frames.glob('*.jpg')));voices=[];known=set();loaded=len(performances);i=0;started=time.monotonic()
    video=args.output/'picture-only.mp4'
    segments=args.output/'render-segments';segments.mkdir(exist_ok=True)
    if video.exists():
        target=segments/f'part-{len(list(segments.glob("*.mp4"))):04d}.mp4'
        subprocess.run([ff,'-v','error','-y','-i',str(video),'-map','0:v','-c','copy','-movflags','+faststart',str(target)],check=True)
    previous=sorted(segments.glob('*.mp4'))
    for part in previous:
        probe=subprocess.run([ff,'-v','error','-i',str(part),'-map','0:v','-f','null','-','-progress','pipe:1'],capture_output=True,check=True,text=True)
        i+=int(re.findall(r'frame=(\d+)',probe.stdout)[-1])
    if i:
        for first in range(0,i,240):await page.evaluate('(a)=>window.offlineAdvance(...a)',[first,min(i,first+240)])
        print(json.dumps({'resumed_frames':i,'resumed_seconds':i/fps}),flush=True)
    encoder=subprocess.Popen([ff,'-v','error','-y','-f','image2pipe','-framerate',str(fps),'-vcodec','mjpeg','-i','pipe:0',
        '-an','-c:v','libx264','-threads','2','-preset','fast','-crf','17','-pix_fmt','yuv420p','-movflags','frag_keyframe+empty_moov',str(video)],stdin=subprocess.PIPE)
    try:
        while True:
            state=json.loads((args.replay/'viewing-state.json').read_text(encoding='utf-8'))
            timeline=PlaybackTimeline(state.get('pauses',[]))
            new=[{**e,'at':e['wall']} for e in state['performances'][loaded:]]
            if new:await page.evaluate('items=>window.appendPerformances(items)',new)
            loaded=len(state['performances'])
            for event in state['events']:
                if not event.get('audio') or event['id'] in known:continue
                path=args.replay/Path(event['audio']).name;samples=pcm_audio(ff,path)
                for caption in event['captions']:
                    lines=await page.evaluate('text=>window.captionLineCount(text)',caption['text'])
                    if lines>4:raise ValueError(f'Caption overflow: event {event["id"]}, {lines} lines')
                voices.append({**event,'at':event.get('output_at',event['cursor']),'samples':samples,'duration':len(samples)/8000,'path':path});known.add(event['id'])
            duration=max([timeline.output_at(args.seconds)]+[v['at']+v['duration'] for v in voices])+.15
            total=math.ceil(duration*fps)
            safe=total if state.get('complete') else max(0,math.floor(timeline.output_at(state['cursor'])*fps))
            if i>=safe:
                if state.get('complete'):break
                await asyncio.sleep(2);continue
            limit=min(safe,i+120)
            while i<limit:
                t=i/fps;active=next((v for v in voices if v['at']<=t<v['at']+v['duration']),None);caption='';mouth=0
                if active:
                    vt=t-active['at'];caption=next((c['text'] for c in active['captions'] if c['start']<=vt<=c['end']),'')
                    center=int(vt*8000);samples=active['samples'][max(0,center-160):center+160]
                    if samples:mouth=min(1,7*math.sqrt(sum((s/32768)**2 for s in samples)/len(samples)))
                index=min(count,int(min(timeline.source_at(t),args.seconds)*fps)+1)
                data=await page.evaluate('(a)=>window.offlineFrame(...a)',[t,f'/source-frame/{index:06d}.jpg',caption,mouth])
                encoder.stdin.write(base64.b64decode(data.split(',',1)[1]));i+=1
            if i%120==0:
                progress={'rendered_seconds':i/fps,'watched_seconds':state['cursor'],'frames':i,'wall_seconds':round(time.monotonic()-started,1)}
                (args.output/'render-progress.json').write_text(json.dumps(progress),encoding='utf-8')
                print(json.dumps(progress),flush=True)
        encoder.stdin.close()
        if encoder.wait():raise RuntimeError('Video encoding failed')
    except BaseException:
        encoder.kill();encoder.wait();raise
    duration=i/fps
    parts=previous+[video]
    # Non-overlapping speech is written sequentially. No per-voice delay buffers.
    track=args.output/'speech.f32le';position=0;rate=48000;total_samples=round(duration*rate)
    with track.open('wb') as dest:
        def silence(samples):
            while samples>0:
                n=min(samples,rate);dest.write(bytes(n*8));samples-=n
        for voice in voices:
            target=round(voice['at']*rate)
            if target<position:raise ValueError('Overlapping speech on committed timeline')
            silence(target-position)
            raw=subprocess.run([ff,'-v','error','-i',str(voice['path']),'-af','volume=1.4','-f','f32le','-ac','2','-ar',str(rate),'pipe:1'],capture_output=True,check=True).stdout
            dest.write(raw);position=target+len(raw)//8
        silence(max(0,total_samples-position))
    audio=args.output/'mixed.wav'
    original=source_audio(ff,args.video,args.output/'original.f32le',0,args.seconds,state.get('pauses',[]))
    filters=f'[0:a]apad,atrim=duration={duration}[original];[original][1:a]amix=inputs=2:duration=first:normalize=0[mix]'
    subprocess.run([ff,'-v','error','-y','-f','f32le','-ar',str(rate),'-ac','2','-i',str(original),'-f','f32le','-ar',str(rate),'-ac','2','-i',str(track),'-filter_complex',filters,'-map','[mix]','-c:a','pcm_f32le',str(audio)],check=True)
    out=args.output/'大肥鱼陪看-第一季01完整版.mp4'
    if previous:
        # Independently flush each H.264 decoder; concatenating compressed
        # fragments can carry B-frame timestamp offsets across the boundary.
        inputs=[];filters=[]
        for n,part in enumerate(parts):
            inputs+=['-i',str(part)];filters.append(f'[{n}:v]setpts=PTS-STARTPTS[p{n}]')
        inputs+=['-i',str(audio)]
        filters.append(''.join(f'[p{n}]' for n in range(len(parts)))+f'concat=n={len(parts)}:v=1:a=0,settb=1/24,setpts=N[v]')
        filters.append(f'[{len(parts)}:a]alimiter=limit=0.891251:level=0:latency=1[a]')
        subprocess.run([ff,'-v','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]',
            '-r','24','-fps_mode','cfr','-c:v','libx264','-threads','2','-preset','fast','-crf','17','-pix_fmt','yuv420p',
            '-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(out)],check=True)
    else:
        subprocess.run([ff,'-v','error','-y','-i',str(video),'-i',str(audio),'-map','0:v','-map','1:a','-c:v','copy',
            '-af','alimiter=limit=0.891251:level=0:latency=1','-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(out)],check=True)
    report={'mode':'offline_fixed_step_follow','fps':fps,'frames':i,'duration':duration,'source_end':args.seconds,'source_audio_gain':1,
            'pauses':state.get('pauses',[]),'speech_count':len(voices),'performances':loaded,'speech':[{'id':v['id'],'at':v['at'],'duration':v['duration'],'captions':v['captions']} for v in voices]}
    (args.output/'render-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.output/'performance-execution.json').write_text(json.dumps(await page.evaluate('window.clockSnapshot().metrics.performances'),ensure_ascii=False),encoding='utf-8')
    print('FULL EPISODE RENDER COMPLETE',flush=True)
