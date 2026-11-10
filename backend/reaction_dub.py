"""Offline actor-directed dubbing. Keeps source decisions, uses only past evidence."""
import argparse, asyncio, copy, json, math, os, shutil, subprocess, sys
from pathlib import Path
from reaction_episode import save, nonempty_response
from reaction_server import Reactor
from live_pilot_chat import generator
from reaction_pacing import PlaybackTimeline, REVIEW_PROMPT, parse_review
from reaction_tools import execute_playback_tool
from reaction_timing import validate_timing


def parse_delivery(raw):
    obj,_=json.JSONDecoder().raw_decode(raw[raw.index('{'):])
    vector=obj.get('emotion_vector')
    if not isinstance(obj.get('intent'),str) or not isinstance(vector,list) or len(vector)!=8 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in vector):
        raise ValueError('Choose a valid delivery vector')
    return obj


async def main(a):
    a.output.mkdir(parents=True,exist_ok=True)
    original=json.loads((a.viewing/'viewing-state.json').read_text('utf-8'))
    v4=original.get('input',{}).get('interaction_version')==4
    if not original.get('complete'):raise ValueError('Finish watching before final dubbing')
    system,prefix,key=generator.load_context(a.home,a.persona,scene='reaction_offline')
    engine=Reactor(a.home,a.persona,max_calls=600)
    voice_settings=json.loads(a.voice_settings.read_text('utf-8')) if getattr(a,'voice_settings',None) else None
    async def ask(prompt,context,parser):
        context=dict(context);frames=context.pop('_frames',[]);feedback=''
        for attempt in range(3):
            content=json.dumps(context,ensure_ascii=False)
            messages=[{'role':'system','content':system[0]['content']+'\n'+prompt+feedback},{'role':'user','content':([{'type':'text','text':content}]+frames) if frames else content}]
            if prefix.get('enabled'):messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
            async def request():return (await engine.complete(messages,key))[0]
            raw=await nonempty_response(request)
            try:return parser(raw)
            except (ValueError,TypeError,KeyError) as exc:
                if attempt==2:raise
                feedback='\n上次格式或时序未通过校验，请自己修正：'+str(exc)+'。上次选择：'+raw
    state=copy.deepcopy(original);state.update(events=[],performances=[],playbacks=[],pauses=[],tool_receipts=[],voice_until=0,complete=False)
    state.pop('playback_tools',None)
    # Tool idempotency receipts belong to the estimated timeline, not the final one.
    for k in list(state):
        if k not in original:continue
        if k in ('tool_results','playback_tool_results','applied_tools'):state.pop(k,None)
    studio_cfg=json.loads(a.studio_config.read_text('utf-8'))
    timings=json.loads(a.timing_plan.read_text('utf-8')) if getattr(a,'timing_plan',None) else {}
    for index,source in enumerate(original['events']):
        event=copy.deepcopy(source);event.pop('tool_result',None);event.pop('duration_estimated',None)
        onset=event['cursor']
        if str(event['id']) in timings and event.get('audio'):
            plan=timings[str(event['id'])]
            event['reaction_timing']=validate_timing(plan,evidence_ready=plan['evidence_ready_at'],considered_at=max(event['cursor'],plan['considered_at']),source_end=original['input']['seconds'])
            onset=event['reaction_timing']['speak_at']
        at=PlaybackTimeline(state['pauses']).output_at(onset);event['output_at']=at
        if event.get('audio'):
            receipt=a.output/f'dub-{event["id"]}.json'
            if receipt.exists():
                chosen=json.loads(receipt.read_text('utf-8'))
            else:
                text=event['text'];reviews=[]
                evidence={'source_seconds':event['cursor'],'seen_story':event.get('story'),'observation':event.get('observation'),'your_original_intent':event.get('topic'),
                          'recent_spoken':[{'text':e['text'],'duration':e['duration']} for e in state['events'] if e.get('audio')][-5:]}
                for revision in range(4):
                    if voice_settings:
                        from reaction_voice import prepare_voice
                        audio=await prepare_voice(text,voice_settings,a.output.parent/'voice-cache',ask,evidence)
                        delivery=audio['delivery']
                    else:
                        delivery=await ask('你在给自己已经选定的陪看反应配音。自己决定语气，不改台词，不预设情绪。只返回JSON {"intent":"你想怎么说","emotion_vector":[8个0到1的数字]}。IndexTTS2八维依次是高兴、愤怒、悲伤、害怕、厌恶、低落、惊讶、平静，可以很轻也可以明显，不必夸张。',dict(evidence,text=text),parse_delivery)
                        project=f'reaction-{event["id"]}-r{revision}'
                        request={'text':text,'reference_asset':a.reference,'emotion_vector':delivery['emotion_vector']}
                        work=Path(studio_cfg['workspace'])/project; (work/'jobs').mkdir(parents=True,exist_ok=True)
                        save(work/'jobs'/'dub.json',request)
                        worker=a.studio_backend/'audio_worker.py'
                        # Existing reusable preparation owns TTS, cache, alignment and audio integrity.
                        subprocess.run([a.audio_python,str(worker),'--config',str(a.studio_config),'--project',project,'--job','dub'],check=True,env={**os.environ,'PYTHONUTF8':'1'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                        audio=json.loads((work/'prepared.json').read_text('utf-8'))
                    conflict=max(0,state['voice_until']-at)
                    if v4:
                        from reaction_experience import ARRANGE_PROMPT,playback_constraints
                        constraints=playback_constraints(at,audio['duration'],state['voice_until'],PlaybackTimeline(state['pauses']).output_at(original['input']['seconds']),event.get('delivery','overlay'))
                        if not any(constraints.values()):
                            review={'choice':'pause' if event.get('delivery')=='pause' else 'keep','reason':'No playback conflict; preserve original wording and actor-selected delivery','text':''}
                        else:
                            review=await ask(ARRANGE_PROMPT,dict(evidence,your_text=text,actual_voice_seconds=audio['duration'],constraints=constraints,selected_delivery=event.get('delivery'),prior_reviews=reviews),parse_review)
                    else:
                        review=await ask(REVIEW_PROMPT+'\n这是离线配音后的核对，只用给出的已看信息。你可以取消或缩短，不为容纳长话自动暂停。若存在与上一句重叠，keep不能通过；若选择暂停但上一句仍在说，也不能通过，请自己缩短/取消当前或另行处理。不要补后续剧情。'+('这次请选择keep/pause/defer作为最终决定。' if revision==3 else ''),dict(evidence,your_text=text,actual_voice_seconds=audio['duration'],previous_voice_overlap_seconds=conflict,selected_delivery=event.get('delivery'),prior_reviews=reviews),parse_review)
                    reviews.append({'delivery':delivery,'text':text,'duration':audio['duration'],'review':review})
                    if review['choice']=='shorten' and revision<3:text=review['text'];continue
                    if conflict and review['choice']!='defer' and not (v4 and voice_settings and voice_settings.get('autonomous_timing',True)):
                        raise ValueError('Actor selected overlapping speech; needs explicit revision')
                    if review['choice']=='shorten':raise ValueError('No final pacing choice')
                    chosen={'text':text,'audio':audio,'delivery':delivery,'review':review,'reviews':reviews};save(receipt,chosen);break
            event.update(text=chosen['text'],voice_delivery=chosen['delivery'],dubbing_reviews=chosen['reviews'])
            review=chosen['review']
            if voice_settings and voice_settings.get('autonomous_timing',True) and review['choice']!='defer' and str(event['id']) not in timings:
                from reaction_onset import choose_onset
                if 'timing' not in chosen:
                    timing_event={**event,'duration':chosen['audio']['duration'],'delivery':'pause' if review['choice']=='pause' else 'overlay','enforce_source_end':v4}
                    chosen['timing']=await choose_onset(timing_event,original,a.viewing,ask,state['voice_until'],state['pauses'])
                    save(receipt,chosen)
                event['reaction_timing']=chosen['timing']
                if chosen['timing']['choice']=='defer':review={'choice':'defer','reason':chosen['timing']['reason']}
                else:
                    onset=chosen['timing']['speak_at'];at=PlaybackTimeline(state['pauses']).output_at(onset);event['output_at']=at
            if review['choice']=='defer':
                event.pop('audio',None);event['deferred']=True;event['performance']=None
                state.setdefault('deferred',[]).append({'source':event['cursor'],'text':event['text'],'reason':review['reason']})
            else:
                prepared=chosen['audio'];path=Path(prepared['path']) if prepared.get('path') else Path(studio_cfg['workspace'])/'generated'/(prepared['audio']+'.wav')
                target=a.output/f'voice-{event["id"]}.wav';shutil.copyfile(path,target)
                event.update(audio='/audio/'+target.name,duration=prepared['duration'],captions=prepared['subtitles'],delivery='pause' if review['choice']=='pause' else 'overlay')
                # Fit short utterances on the full multiline panel instead of splitting into small pages.
                if len(event['text'])<=112:event['captions']=[{'start':0,'end':event['duration'],'text':event['text']}]
                call={'name':'reaction_pause','arguments':{'reason':review['reason'],'resume':'speech_end'}} if review['choice']=='pause' else {'name':'reaction_continue','arguments':{}}
                event['tool_result']=execute_playback_tool(state,call,call_id=f'dub-{event["id"]}',cursor=onset,speech_duration=event['duration'])
                event['playback_tool']=call
                state['voice_until']=at+event['duration']
                state['playbacks'].append({'id':event['id'],'wall':at,'source':onset,'text':event['text']})
        state['events'].append(event)
        state['performances'].append({'wall':at,'source':onset,'selected':event['performance']})
        save(a.output/'viewing-state.json',state)
        print(json.dumps({'dubbed_source':event['cursor'],'spoken':bool(event.get('audio'))}),flush=True)
    state['complete']=True;state['dubbing']={'provider':'IndexTTS2','prefixEnabled':bool(prefix.get('enabled')),'timing':'measured','source':str(a.viewing)}
    state['performances'].sort(key=lambda p:p['wall'])
    state['playbacks'].sort(key=lambda p:p['wall'])
    save(a.output/'viewing-state.json',state)
    save(a.output/'decisions.json',{'speed':1,'prefixEnabled':bool(prefix.get('enabled')),'events':state['events']})
    save(a.output/'clock-metrics.json',{'speed':1,'playbacks':state['playbacks'],'performances':state['performances'],'pauses':state['pauses']})


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('viewing','output','home','persona','studio-config','studio-backend'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--audio-python',required=True);p.add_argument('--reference',default='voice-reference')
    p.add_argument('--timing-plan',type=Path)
    p.add_argument('--voice-settings',type=Path)
    asyncio.run(main(p.parse_args()))
