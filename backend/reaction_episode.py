"""Resumable chronological viewing. Source progress waits for understanding.

Produces the same speech/performance timeline consumed by the fixed-step renderer.
Only this production directory is written; persona and formal memory stay read-only.
"""
import argparse, asyncio, base64, hashlib, json, math, subprocess, time
from pathlib import Path
import edge_tts, imageio_ffmpeg
from reaction_server import Reactor
from reaction_intent import INTENT_PROMPT, parse_intent
from reaction_job_control import pending_control
from reaction_tools import TOOLS, execute_playback_tool
from reaction_pacing import PACING_PROMPT, SPEECH_PROMPT, REVIEW_PROMPT, parse_review, PlaybackTimeline, pause_duration
from reaction_performance import PERFORMANCE_PROMPT, validate_performance
from reaction_render import caption_pages
from reaction_frame_render import pcm_audio
from live_pilot_chat import generator
from reaction_attention import OBSERVE_PROMPT, TURN_PROMPT, parse_observation, heard_until, speech_awareness, turn_signal


async def nonempty_response(request):
    """Retry failed transport/output, without inventing speech or changing intent."""
    for attempt in range(3):
        try:
            value = await request()
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Model returned empty content')
            return value
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(2 * (attempt + 1))


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    # Windows may briefly deny rename while a reader has the old file open.
    for attempt in range(40):
        try:
            temporary.replace(path);break
        except PermissionError:
            if attempt==39:raise
            time.sleep(.025)


def frame_batch(cursor, end, rewind=0):
    # Frame i is sampled at (i-1)/4; never include a later frame.
    last = min(math.floor(cursor * 4), math.ceil(end * 4)-1)
    first = max(0, last-7)
    if rewind:
        first = max(0, last-math.floor(rewind*4))
    indices = list(range(first,last+1))
    if len(indices)>8:
        indices = [indices[round(i*(len(indices)-1)/7)] for i in range(8)]
    return [(i+1,i/4) for i in indices]


def performance(intent):
    value=intent.get('performance')
    if isinstance(value,dict):
        value=dict(value)
        duration=value.get('duration',3)
        if isinstance(duration,(int,float)) and not isinstance(duration,bool) and math.isfinite(duration):
            value['duration']=min(10,max(1,duration))
    return validate_performance(value)


async def main(args):
    args.output.mkdir(parents=True,exist_ok=True)
    ff=imageio_ffmpeg.get_ffmpeg_exe(); frames=args.output/'observed-frames'
    signature={'video':str(args.video.resolve()),'size':args.video.stat().st_size,'seconds':args.seconds,'step':args.step,'pacing_version':2}
    hearing_path = getattr(args, 'hearing', None)
    hearing = json.loads(hearing_path.read_text(encoding='utf-8')) if hearing_path else None
    if hearing is not None:
        if not hearing.get('complete') or hearing['source'] != str(args.video.resolve()) or hearing['seconds'] < args.seconds:
            raise ValueError('Hearing evidence does not match source')
        signature.update(attention_version=3, hearing=str(hearing_path.resolve()),hearing_sha256=hashlib.sha256(hearing_path.read_bytes()).hexdigest())
    checkpoint=args.output/'viewing-state.json'
    if checkpoint.exists():
        state=json.loads(checkpoint.read_text(encoding='utf-8'))
        if state['input']!=signature:raise ValueError('Resume source differs from checkpoint')
    else:
        state={'input':signature,'cursor':0,'events':[],'playbacks':[],'performances':[],
               'plot_memory':'','memory_archives':[],'summarized_count':0,'voice_until':0,'calls':0,'usage':0,'pending':None,'pauses':[],'deferred':[]}
        save(checkpoint,state)
    frames.mkdir(exist_ok=True)
    if not (frames/'complete.json').exists():
        subprocess.run([ff,'-v','error','-y','-i',str(args.video),'-t',str(args.seconds),
                        '-vf','fps=4,scale=960:540','-q:v','3',str(frames/'%06d.jpg')],check=True)
        save(frames/'complete.json',signature)
    system,prefix,key=generator.load_context(args.home,args.persona,scene='reaction_offline')
    engine=Reactor(args.home,args.persona,max_calls=2400)
    engine.calls=state['calls'];engine.usage=state['usage']
    gate=system[0]['content']+'\n'+INTENT_PROMPT[INTENT_PROMPT.index('这一步只作内部选择'):]
    gate+='\n当前是在陪搭档一起看影片，观看进度会等待处理完再继续。这次收到已播放的新画面，请按自己的想法决定：有想说的话就选speak；想接着看就选continue；想重看就选replay。三种选择都正常。表达不要求先解开剧情疑问，不需要证明有必要发言；也不需要为了回应这次调用而说话。playback是正在说的话和还没说出的想法。正在说话时，新的想法先保留；说完后由你结合最新画面决定是否还想说，也可改变或放下先前想法。'
    gate+='\n'+PACING_PROMPT+'\n'+PERFORMANCE_PROMPT+'\n可调用的播放工具：'+json.dumps(TOOLS,ensure_ascii=False)
    if hearing is not None:
        gate = system[0]['content']+'\n'+INTENT_PROMPT+'\n'+TURN_PROMPT+'\n'+PACING_PROMPT+'\n'+PERFORMANCE_PROMPT
        gate = gate.replace('没有原声音频输入，不臆测音色。', '有带时间戳的机器听觉证据，原始波形未直接传给你。声纹与角色归属可能有误，不把候选当事实。')
    async def complete(messages, structured=False):
        async def request():
            return (await engine.complete(messages,key,structured=structured))[0]
        return await nonempty_response(request)
    def prefixed(messages):
        if prefix.get('enabled'):
            messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
        return messages
    async def selected_performance(intent):
        try:return performance(intent)
        except ValueError:
            for attempt in range(3):
                raw=await complete(prefixed([{'role':'system','content':system[0]['content']+'\n'+PERFORMANCE_PROMPT+'\n你刚选的表演无法执行，请自己从可用选项重新选择。只返回JSON {"performance":{...}}，不改台词或剧情。'},
                    {'role':'user','content':json.dumps({'your_intent':intent},ensure_ascii=False)}]))
                try:
                    start=raw.index('{');obj,_=json.JSONDecoder().raw_decode(raw[start:])
                    return performance(obj)
                except (ValueError,TypeError):
                    if attempt==2:raise
    def checkpoint_now():
        state.update(calls=engine.calls,usage=engine.usage)
        save(checkpoint,state)
        save(args.output/'decisions.json',{'speed':1,'prefixEnabled':bool(prefix.get('enabled')),'events':state['events']})
        save(args.output/'clock-metrics.json',{'speed':1,'playbacks':state['playbacks'],'performances':state['performances'],'pauses':state['pauses']})
    while state['cursor']<args.seconds:
        cursor=min(args.seconds,state['cursor']+args.step)
        started=time.monotonic();event=state.get('inflight')
        if event is None:
            past=state['events'];output_at=PlaybackTimeline(state['pauses']).output_at(cursor);busy=output_at<state['voice_until']
            control=pending_control(args.output,state) if not busy else None
            content=[{'type':'text','text':json.dumps({'cursor':cursor,'viewed_up_to':cursor,
                'plot_memory':state['plot_memory'],
                'recent_observations':[{k:e.get(k) for k in ('cursor','story','interest')} for e in past[-12:]],
                'actually_spoken':[{'at':e['cursor'],'text':e['text']} for e in past if e.get('audio')][-5:],
                'playback':{'busy':busy,'currentlySpeaking':next((e.get('text','') for e in reversed(past) if e.get('audio') and e.get('output_at',e['cursor'])<=output_at<e.get('output_at',e['cursor'])+e['duration']),''),
                            'pendingThought':state['pending']},'deferred_to_afterword':state['deferred'][-5:],'recent_delivery':[{'source':e['cursor'],'delivery':e.get('delivery'),'duration':e.get('duration')} for e in past if e.get('audio')][-5:]},ensure_ascii=False)}]
            batch=frame_batch(cursor,args.seconds)
            for index,at in batch:
                data=base64.b64encode((frames/f'{index:06d}.jpg').read_bytes()).decode()
                content.extend([{'type':'text','text':f'已看画面 {at:.2f} 秒'},
                                {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+data}}])
            if control:content.append({'type':'text','text':json.dumps({'main_dialogue_tool_request':control,'instruction':'这是主对话的你选择的播放工具；只依据已看材料执行，不从问题猜测后续剧情。'},ensure_ascii=False)})
            observation = None; signal = None
            if hearing is not None:
                cues = heard_until(hearing, cursor)
                recent_cues = cues[-12:]
                evidence = {'cursor':cursor, 'previous_unit':state.get('observation_unit'),
                            'plot_memory':state['plot_memory'], 'hearing':recent_cues,
                            'speaker_hypotheses':{k:v[-3:] for k,v in state.get('speaker_hypotheses',{}).items()},
                            'recent_observations':[e.get('observation') for e in past[-12:] if e.get('observation')]}
                observation_content = [{'type':'text','text':json.dumps(evidence,ensure_ascii=False)}] + content[1:]
                for attempt in range(3):
                    observed = await complete([{'role':'system','content':OBSERVE_PROMPT},{'role':'user','content':observation_content}],structured=True)
                    try:
                        observation = parse_observation(observed,recent_cues);break
                    except ValueError:
                        if attempt == 2:raise
                signal = turn_signal(observation,state.get('considered_units',[]))
                content.append({'type':'text','text':json.dumps({'accumulated_observation':observation,'hearing':recent_cues,
                    'speech_awareness':speech_awareness(past,output_at),
                    'since_last_deliberation':[e.get('observation') for e in past if e['cursor']>state.get('last_deliberation_at',0)][-20:]},ensure_ascii=False)})
            if hearing is not None and (busy or not (signal or control)):
                raw=json.dumps({'action':'continue','story':observation['understanding'][:1800],'interest':observation['change'][:400],
                    'reason':'持续观察，尚无新的完整事件或突发变化供自主审议' if not busy else '持续观察，发言仍在进行；积累理解，不排队新台词',
                    'topic':'','performance':None},ensure_ascii=False)
            else:
                raw=await complete(prefixed([{'role':'system','content':gate},{'role':'user','content':content}]))
            repaired=raw
            for repair in range(4):
                try:
                    intent=parse_intent(repaired,0,cursor);break
                except ValueError:
                    save(args.output/f'intent-format-{len(past)}-{repair}.json',{'cursor':cursor,'raw':repaired})
                    if repair==3:raise
                    # Repair serialization only; no replacement speaking decision.
                    repaired=await complete([{'role':'system','content':f'只把给定结果整理成合法JSON，保持原有选择和含义，不另作决定。focus_at必须是0至{cursor}之间的数字秒数，不是字符串或分秒记法。seconds必须为数字，不能为null。story最多1800字，interest最多400字，reason和topic各最多600字。'+INTENT_PROMPT},
                                            {'role':'user','content':repaired}],structured=True)
            if control:
                intent.update(action='speak' if control['action']=='pause_analysis' else 'replay',focus_at=cursor)
                if control['action']=='pause_analysis':intent.update(topic=control['topic'],delivery='pause',pause_reason=control['topic'])
                else:intent['seconds']=control['seconds']
            event={'id':len(past),'cursor':cursor,'output_at':output_at,'frames':[at for _,at in batch],'raw_intent':raw,**intent}
            if observation is not None:
                event.update(observation=observation,hearing_ids=[c['id'] for c in recent_cues],
                             deliberated=not busy and bool(signal or control),turn_signal=signal)
            if control:event['control_id']=control['id']
            event['performance']=await selected_performance(intent)
            if intent['action']=='replay':
                event['replay_tool_result']=execute_playback_tool(state,{'name':'reaction_replay','arguments':{'seconds':intent['seconds']}},call_id=f"replay-{event['id']}",cursor=cursor)
                replay_content=[{'type':'text','text':f'按你的选择重看已看到的 {max(0,cursor-intent["seconds"]):.2f} 至 {cursor:.2f} 秒。没有新剧情。'}]
                for index,at in frame_batch(cursor,args.seconds,intent['seconds']):
                    replay_content.extend([{'type':'text','text':f'{at:.2f} 秒'}, {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode((frames/f'{index:06d}.jpg').read_bytes()).decode()}}])
                reread=await complete(prefixed([{'role':'system','content':gate},{'role':'user','content':content+replay_content}]))
                revision=parse_intent(reread,0,cursor)
                event.update(replay_request=intent,raw_replay=reread,**revision)
                event['performance']=await selected_performance(revision)
            if event['action']=='speak' and not busy:
                expression=system[0]['content']+'\n'+SPEECH_PROMPT+'\n'+PACING_PROMPT
                if hearing is not None:
                    expression=expression.replace('没有原声音频输入，不臆测音色。','听觉证据来自带时间戳的机器转写和声纹候选，不能把不确定的角色归属说成事实。')
                text=await complete(prefixed([{'role':'system','content':expression},{'role':'user','content':content+[{'type':'text','text':json.dumps({'your_intent':event},ensure_ascii=False)}]}]))
                if not text.strip():raise ValueError('Empty chosen speech')
                event['text']=text
            state['inflight']=event;checkpoint_now()
        if event.get('text'):
            while not event.get('pacing_final'):
                revision=len(event.get('pacing_reviews',[]))
                name=f"voice-{event['id']}-r{revision}";audio=args.output/f'{name}.mp3';meta=args.output/f'{name}.jsonl'
                for attempt in range(3):
                    try:
                        if not (audio.exists() and meta.exists() and meta.stat().st_size):
                            await asyncio.wait_for(edge_tts.Communicate(event['text'],'zh-CN-XiaoyiNeural',rate='+10%',pitch='+14Hz',boundary='WordBoundary').save(str(audio),str(meta)),60)
                        words=[json.loads(line) for line in meta.read_text(encoding='utf-8').splitlines()]
                        duration=len(pcm_audio(ff,audio))/8000
                        if duration<=0:raise ValueError('Empty audio')
                        event.update(audio='/audio/'+audio.name,captions=caption_pages(event['text'],words),duration=duration)
                        break
                    except Exception:
                        if attempt==2:raise
                        audio.unlink(missing_ok=True);meta.unlink(missing_ok=True)
                        await asyncio.sleep(2)
                review_context={'source':cursor,'viewed_up_to':cursor,'topic':event.get('topic'),
                    'your_text':event['text'],'actual_voice_seconds':duration,'selected_delivery':event.get('delivery','overlay'),
                    'pause_reason':event.get('pause_reason',''),'prior_reviews':event.get('pacing_reviews',[]),
                    'recent_delivery':[{'source':e['cursor'],'delivery':e.get('delivery'),'duration':e.get('duration')} for e in state['events'] if e.get('audio')][-5:]}
                review_prompt=REVIEW_PROMPT+'\n播放工具：'+json.dumps(TOOLS,ensure_ascii=False)+'\n若choice=pause，请同时返回tool_call={"name":"reaction_pause","arguments":{"reason":"你暂停的原因","resume":"speech_end"}}；keep对应reaction_continue，arguments为空对象；shorten/defer不调用播放工具。'+('已自行修改两次，请在keep/pause/defer中作最终决定。' if revision>=2 else '')
                for attempt in range(3):
                    if event.get('control_id') and event.get('delivery')=='pause':
                        review={'choice':'pause','reason':event['pause_reason'],'text':'','tool_call':{'name':'reaction_pause','arguments':{'reason':event['pause_reason'],'resume':'speech_end'}}}
                        break
                    raw=await complete(prefixed([{'role':'system','content':system[0]['content']+'\n'+review_prompt},
                        {'role':'user','content':json.dumps(review_context,ensure_ascii=False)}]))
                    try:
                        review=parse_review(raw)
                        if revision>=2 and review['choice']=='shorten':raise ValueError('Expected final pacing choice')
                        break
                    except ValueError:
                        if attempt==2:raise
                event.setdefault('pacing_reviews',[]).append({'text':event['text'],'duration':duration,'decision':review})
                if review['choice']=='shorten':
                    event['text']=review['text'];event.pop('audio',None)
                else:
                    event['pacing_final']=True
                    if review['choice']=='defer':
                        event.pop('audio',None);event['deferred']=True
                    else:
                        event['delivery']='pause' if review['choice']=='pause' else 'overlay'
                        event['pause_reason']=review['reason'] if review['choice']=='pause' else ''
                checkpoint_now()
            if event.get('audio'):
                decision=event['pacing_reviews'][-1]['decision']
                selected=decision.get('tool_call')
                if selected is None:  # Older checkpoints remain replayable.
                    selected={'name':'reaction_pause','arguments':{'reason':event['pause_reason'],'resume':'speech_end'}} if event['delivery']=='pause' else {'name':'reaction_continue','arguments':{}}
                expected='reaction_pause' if event['delivery']=='pause' else 'reaction_continue'
                if selected.get('name')!=expected:raise ValueError('Pacing choice and tool call disagree')
                event['playback_tool']=selected
                event['tool_result']=execute_playback_tool(state,selected,call_id=f"speech-{event['id']}",cursor=cursor,speech_duration=event['duration'])
                state['voice_until']=event['output_at']+event['duration']
                state['playbacks'].append({'id':event['id'],'wall':event['output_at'],'source':cursor,'text':event['text']})
            elif event.get('deferred'):
                state['deferred'].append({'source':cursor,'topic':event.get('topic'),'text':event['text']})
        state['pending']={'topic':event.get('topic'),'at':cursor} if event['action']=='speak' and not event.get('audio') and not event.get('deferred') else None
        event['processing_seconds']=time.monotonic()-started
        state['events'].append(event)
        if event.get('observation'):
            state['observation_unit']=event['observation']
            for attribution in event['observation'].get('attributions',[]):
                voice = attribution.get('voice_candidate')
                if voice:
                    history=state.setdefault('speaker_hypotheses',{}).setdefault(voice,[])
                    record={'at':cursor,**attribution}
                    if not history or any(history[-1].get(k)!=record.get(k) for k in ('cue_id','character','confidence','reason')):
                        history.append(record)
            if event.get('deliberated'):
                state['last_deliberation_at']=cursor
                if event.get('turn_signal'):state.setdefault('considered_units',[]).append(event['turn_signal'])
        state['performances'].append({'wall':event['output_at'],'source':cursor,'selected':event['performance']})
        state['cursor']=cursor;state.pop('inflight',None);checkpoint_now()
        # Compress chronological evidence, not personality or speaking instructions.
        pending=state['events'][state['summarized_count']:-12]
        if len(pending)>=24:
            memory_input={'previous_memory':state['plot_memory'],'new_observations':[{k:e.get(k) for k in ('cursor','story','interest')} for e in pending]}
            raw=await complete([{'role':'system','content':'更新已看剧情的连续记忆。只依据输入，保留人物关系、因果、未解问题、纠正及来源时间。区分事实与推断，不补未来剧情，不评价说话风格。只返回JSON {"summary":"不超过1400字"}。'},
                                {'role':'user','content':json.dumps(memory_input,ensure_ascii=False)}],structured=True)
            summary=json.loads(raw)['summary']
            if not isinstance(summary,str) or not summary.strip():raise ValueError('Invalid plot memory')
            state['memory_archives'].append({'through':pending[-1]['cursor'],'sources':[e['id'] for e in pending],'summary':summary})
            state['plot_memory']=summary;state['summarized_count']+=len(pending);checkpoint_now()
        print(json.dumps({'cursor':cursor,'total':args.seconds,'action':event['action'],'spoken':bool(event.get('audio')),'speeches':len(state['playbacks']),'calls':engine.calls},ensure_ascii=False),flush=True)
    state['complete']=True;checkpoint_now();print('VIEWING COMPLETE',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--home',type=Path,required=True);p.add_argument('--persona',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=1420);p.add_argument('--step',type=float,default=2)
    p.add_argument('--hearing',type=Path)
    a=p.parse_args()
    if not 0<a.seconds<=14400 or not .25<=a.step<=10:p.error('Invalid viewing bounds')
    asyncio.run(main(a))
