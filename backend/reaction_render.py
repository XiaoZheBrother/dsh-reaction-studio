"""Render a sequential watch timeline at normal source and voice speed."""
import json,subprocess,re,textwrap,html
from pathlib import Path
import imageio_ffmpeg


def stamp(t):
    return f'{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}'

def caption_groups(boundaries, max_chars=24):
    groups=[];current=[];length=0;previous_end=0
    for word in boundaries:
        if word.get('type')!='WordBoundary': continue
        start=word['offset']/10000000;end=start+word['duration']/10000000
        text=html.unescape(word['text'])
        if start<previous_end-.05 or end<start:raise ValueError('Invalid TTS boundaries')
        if current and (length+len(text)>max_chars or start-previous_end>.6):
            groups.append((current[0][0],current[-1][1],''.join(x[2] for x in current)));current=[];length=0
        current.append((start,end,text));length+=len(text);previous_end=end
    if current:groups.append((current[0][0],current[-1][1],''.join(x[2] for x in current)))
    if not groups:raise ValueError('Missing TTS word timing; do not invent subtitle timing')
    return groups


def caption_pages(text, boundaries, capacity=112):
    """Keep punctuation and complete fitting utterances on one multi-line page."""
    words=[w for w in boundaries if w.get('type')=='WordBoundary']
    if not words:raise ValueError('Missing TTS timing')
    end=(words[-1]['offset']+words[-1]['duration'])/10000000
    if len(text)<=capacity:return [{'start':0,'end':end+.25,'text':text}]
    positions=[];cursor=0
    for w in words:
        token=html.unescape(w['text']);pos=text.find(token,cursor)
        if pos<0:raise ValueError('Cannot align subtitle text with TTS words')
        positions.append((pos,w['offset']/10000000));cursor=pos+len(token)
    pages=[];start=0
    while start<len(text):
        stop=min(start+capacity,len(text))
        if stop<len(text):
            breaks=[m.end()+start for m in re.finditer(r'[。！？!?；;，,、]',text[start:stop])]
            if breaks and breaks[-1]>start+capacity//2:stop=breaks[-1]
        t0=next((t for pos,t in positions if pos>=start),end)
        t1=next((t for pos,t in positions if pos>=stop),end+.25)
        pages.append({'start':0 if start==0 else t0,'end':t1,'text':text[start:stop]});start=stop
    return pages


def render(root,avatar,reuse=False):
    data=json.loads((root/'timeline.json').read_text(encoding='utf-8'))
    ff=imageio_ffmpeg.get_ffmpeg_exe();parts=root/'parts';parts.mkdir(exist_ok=True)
    output_time=0;clips=[];speeches=[];subtitles=[]
    def measured_duration(path):
        probe=subprocess.run([ff,'-hide_banner','-i',str(path),'-map','0:v:0','-c','copy','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
        counts=re.findall(r'frame=\s*(\d+)',probe.stderr)
        if not counts: raise ValueError('No frame count')
        return int(counts[-1])/24
    durations=[]
    def run(args):
        if reuse and Path(args[-1]).is_file(): return
        subprocess.run([ff,'-hide_banner','-loglevel','error','-y',*args],check=True)
    for event in data['events']:
        duration=event['source_end']-event['source_start'];part=parts/f'{len(clips):03d}.mp4'
        run(['-ss',str(event['source_start']),'-i',data['source'],'-t',str(duration),'-vf','scale=960:540','-r','24','-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-ar','48000','-ac','2',str(part)])
        clips.append(part);duration=measured_duration(part);durations.append(duration);output_time+=duration
        event['output_trigger']=round(output_time,3)
        if event.get('audio'):
            speeches.append((output_time,root/event['audio'],event['audio_seconds']))
            boundary_file=root/event['boundaries']
            boundaries=[json.loads(line) for line in boundary_file.read_text(encoding='utf-8').splitlines() if line]
            for start,end,text in caption_groups(boundaries):
                if end>event['audio_seconds']+.1:raise ValueError('Caption outside voice')
                formatted=r'\N'.join(textwrap.wrap(text,width=10,break_long_words=True,break_on_hyphens=False))
                subtitles.append(f'Dialogue: 0,{stamp(output_time+start)},{stamp(output_time+end)},Reaction,,0,0,0,,{formatted}')
            if event['placement']=='pause':
                freeze=parts/f'frame-{len(clips):03d}.png'
                run(['-ss',str(max(0,event.get('focus_at',event['source_end'])-1/24)),'-i',data['source'],'-frames:v','1','-vf','scale=960:540',str(freeze)])
                part=parts/f'{len(clips):03d}.mp4';hold=event['audio_seconds']+.35
                run(['-loop','1','-i',str(freeze),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(hold),'-r','24','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac',str(part)])
                clips.append(part);hold=measured_duration(part);durations.append(hold)
                if event.get('focus_at',event['source_end'])<event['source_end']-1:
                    focus=event['focus_at'];label=f'回看 {int(focus//60):02d}:{int(focus%60):02d}'
                    subtitles.append(f'Dialogue: 0,{stamp(output_time)},{stamp(output_time+hold)},Title,,0,0,0,,{{\\pos(30,655)}}{label}')
                output_time+=hold
        event['output_end']=round(output_time,3)
    (root/'render-timeline.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    base=root/'base.mp4'
    inputs=[];filters=[]
    for i,(part,duration) in enumerate(zip(clips,durations)):
        inputs.extend(['-i',str(part)])
        filters.extend([f'[{i}:v]setpts=PTS-STARTPTS[v{i}]',f'[{i}:a]atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]'])
    filters.append(''.join(f'[v{i}][a{i}]' for i in range(len(clips)))+f'concat=n={len(clips)}:v=1:a=1[v][a]')
    run([*inputs,'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac',str(base)])
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reaction,Microsoft YaHei,25,&H00FFFFFF,&H00FFFFFF,&H0028190F,&H0028190F,0,0,0,0,100,100,0,0,1,1,0,5,990,20,0,1
Style: Title,Microsoft YaHei,25,&H00EFD8AA,&H00FFFFFF,&H0028190F,&H0028190F,1,0,0,0,100,100,0,0,1,0,0,7,30,20,25,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    # Explicit positions keep captions clear of the original animation subtitles.
    subtitles=[s.replace(',,0,0,0,,',',,0,0,0,,{\\an5\\pos(1120,430)}') if ',Reaction,' in s else s for s in subtitles]
    (root/'captions.ass').write_text(header+f'Dialogue: 0,0:00:00.00,{stamp(output_time)},Title,,0,0,0,,大肥鱼陪看 · 第一季 01\n'+f'Dialogue: 0,0:00:00.00,{stamp(output_time)},Title,,0,0,0,,{{\\pos(1035,280)}}筱哲的大肥鱼\n'+'\n'.join(subtitles),encoding='utf-8-sig')
    inputs=['-i',str(base),'-loop','1','-i',str(avatar)]
    for _,path,_ in speeches:inputs+=['-i',str(path)]
    filters=['[0:v]pad=1280:720:0:90:color=0x101e30[bg]','[1:v]scale=180:180[av]','[bg][av]overlay=1030:70,ass=captions.ass[v]']
    duck='+'.join(f'between(t,{start:.3f},{start+duration:.3f})' for start,_,duration in speeches) or '0'
    filters.append(f"[0:a]volume='if(gt({duck},0),0.28,1)':eval=frame[original]")
    for i,(start,_,_) in enumerate(speeches):filters.append(f'[{i+2}:a]adelay={round(start*1000)}:all=1,volume=1.5[s{i}]')
    filters.append('[original]'+''.join(f'[s{i}]' for i in range(len(speeches)))+f'amix=inputs={len(speeches)+1}:duration=first:normalize=0,alimiter=limit=0.95[a]')
    subprocess.run([ff,'-hide_banner','-loglevel','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-t',str(output_time),'-c:v','libx264','-preset','veryfast','-crf','19','-c:a','aac','-b:a','192k','-movflags','+faststart',str(root/'大肥鱼离线陪看样片.mp4')],cwd=root,check=True)
    print(json.dumps({'duration':output_time,'reactions':len(speeches),'output':str(root/'大肥鱼离线陪看样片.mp4')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--avatar',type=Path,required=True);p.add_argument('--reuse',action='store_true');a=p.parse_args();render(a.root,a.avatar,a.reuse)
