"""Sequential offline watch: waits per segment, no future frames, no production writes."""
import argparse,asyncio,base64,json,re,subprocess,sys,time
from pathlib import Path
from live_pilot_chat import generator
from reaction_server import Reactor
from reaction_intent import INTENT_PROMPT,parse_intent
import edge_tts,imageio_ffmpeg

async def run(args):
    args.output.mkdir(parents=True,exist_ok=args.resume)
    frames=args.output/'frames';frames.mkdir(exist_ok=args.resume)
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    info=subprocess.run([ffmpeg,'-hide_banner','-i',str(args.video)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    match=re.search(r'Duration: (\d+):(\d+):([\d.]+)',info.stderr)
    if not match: raise ValueError('Cannot read video duration')
    source_duration=int(match[1])*3600+int(match[2])*60+float(match[3])
    if args.seconds>source_duration: raise ValueError('Requested preview exceeds source')
    if not args.resume: subprocess.run([ffmpeg,'-v','error','-i',str(args.video),'-t',str(args.seconds+1),'-vf','fps=1,scale=960:-2','-q:v','3','-start_number','0',str(frames/'%05d.jpg')],check=True)
    system,prefix,key=generator.load_context(args.home,args.persona,scene='reaction_offline')
    system[0]['content'] += '\n'+INTENT_PROMPT
    engine=Reactor(args.home,args.persona)
    history=[];events=[];previous=0;calls=0
    shared={'mode':'offline-sequential','source':str(args.video),'seconds':args.seconds,'step':args.step,'prefixEnabled':bool(prefix.get('enabled')),'voice':'zh-CN-XiaoyiNeural','rate':'+10%','pitch':'+14Hz','events':events}
    if args.resume:
        shared=json.loads((args.output/'timeline.json').read_text(encoding='utf-8'))
        if shared['source']!=str(args.video) or shared['seconds']!=args.seconds or shared['step']!=args.step: raise ValueError('Resume inputs differ')
        events=shared['events'];previous=events[-1]['source_end'] if events else 0
        history=[{'at':e['source_end'],'story':e.get('story',''),'interest':e.get('interest',''),'said':e['text'],'action':e['action']} for e in events]
    for cursor in range(previous+args.step,args.seconds+1,args.step):
        start=previous;replays=0;kind='advance'
        while True:
            indices=sorted(set(round(start+i*(cursor-1-start)/7) for i in range(8)))
            content=[{'type':'text','text':json.dumps({'cursor':cursor,'duration':source_duration,'kind':kind,'played_range':[start,cursor],'previous_reactions':history[-12:]},ensure_ascii=False)}]
            for i in indices:
                if not 0<=i<cursor: raise ValueError('future frame')
                content.extend([{'type':'text','text':f'已播放画面 {i+1} 秒'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode((frames/f'{i:05d}.jpg').read_bytes()).decode()}}])
            messages=system+[{'role':'user','content':content}]
            if prefix.get('enabled'): messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
            raw,tokens=await engine.complete(messages,key);calls+=1
            try:
                intent=parse_intent(raw,start,cursor)
            except ValueError:
                (args.output/f'invalid-{cursor}-{replays}.txt').write_text(raw,encoding='utf-8')
                repair=list(messages[:-1] if prefix.get('enabled') else messages)+[{'role':'assistant','content':raw},{'role':'user','content':'请仅修复选择的JSON格式和已看时间范围。此处不生成口播。'}]
                if prefix.get('enabled'): repair.append(messages[-1])
                raw,tokens=await engine.complete(repair,key);calls+=1
                intent=parse_intent(raw,start,cursor)
            text=''
            if intent['action']=='speak':
                expression=[{'role':'system','content':system[0]['content'].split(INTENT_PROMPT)[0]+ '\n你刚自主决定开口。根据自己的意图和已看画面说出想说的话，直接输出台词；不朗读内部选择、时间戳和分析字段。不需要重复说明每个画面。'} ,{'role':'user','content':content+[{'type':'text','text':json.dumps({'your_intent':intent},ensure_ascii=False)}]}]
                if prefix.get('enabled'): expression.append(messages[-1])
                text,_=await engine.complete(expression,key);calls+=1
                if not text or len(text)>600:raise ValueError('Unexpected spoken output')
            result={**intent,'action':'silent' if intent['action']=='continue' else intent['action'],'text':text}
            event={'index':len(events),'source_start':start,'source_end':cursor,'kind':kind,'frames':[i+1 for i in indices],'raw':raw,**result,'inputTokens':tokens}
            if result['text']:
                audio=args.output/f'voice-{len(events):02d}.mp3'
                metadata=audio.with_suffix('.jsonl')
                await edge_tts.Communicate(result['text'],'zh-CN-XiaoyiNeural',rate='+10%',pitch='+14Hz',boundary='WordBoundary').save(str(audio),str(metadata))
                probe=subprocess.run([ffmpeg,'-hide_banner','-i',str(audio),'-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
                d=re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
                duration=int(d[1])*3600+int(d[2])*60+float(d[3])
                event.update(audio=audio.name,boundaries=metadata.name,audio_seconds=duration,placement='pause' if result['action']=='pause' or duration>7 or cursor==args.seconds else 'overlay')
            events.append(event)
            history.append({'at':cursor,'story':result.get('story',''),'interest':result.get('interest',''),'said':result['text'],'action':result['action']})
            (args.output/'timeline.json').write_text(json.dumps(shared,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'cursor':cursor,'action':result['action'],'chars':len(result['text']),'audio_seconds':event.get('audio_seconds',0),'kind':kind},ensure_ascii=False),flush=True)
            if result['action']!='replay' or replays>=2: break
            start=max(0,cursor-result['seconds']);replays+=1;kind='replay'
        previous=cursor

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--home',type=Path,required=True);p.add_argument('--persona',type=Path,required=True);p.add_argument('--seconds',type=int,default=180);p.add_argument('--step',type=int,default=15)
    p.add_argument('--resume',action='store_true');a=p.parse_args()
    if not 1<=a.step<=30 or a.seconds%a.step or not 1<=a.seconds<=300:p.error('invalid segment bounds')
    asyncio.run(run(a))
