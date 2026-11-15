"""Read-only sequential rehearsal using shared context budgets. No TTS or render."""
import argparse,asyncio,base64,json,math,os,time
from pathlib import Path
from reaction_server import Reactor
from live_pilot_chat import generator
from reaction_episode import save,frame_batch
from reaction_attention import heard_until
from reaction_continuity import UNDERSTAND,DECIDE,ARRANGE,parse_understanding,parse_decision,audio_space,own_space,decision_context
from reaction_attribution import ATTRIBUTION,PUBLIC_EVIDENCE,CHECK,REVISE,update_utterances,recent_utterances,parse_check,enforce_bindings
from reaction_audio_evidence import recent_heard, compact_hearing, narrative_state

async def run(job):
    if job.get('relation_graph'):
        from reaction_relation_run import run as run_relations
        return await run_relations(job)
    root=Path(job['output']);root.mkdir(parents=True,exist_ok=True)
    checkpoint=root/'trace.json'
    state=json.loads(checkpoint.read_text('utf-8')) if checkpoint.exists() else {'cursor':0,'wall':0,'understanding':{},'observations':[],'decisions':[],'attention':'','calls':0,'usage':0,'complete':False}
    system,prefix,key=generator.load_context(Path(job['home']),Path(job['persona']),scene='reaction_offline')
    engine=Reactor(Path(job['home']),Path(job['persona']),max_calls=600)
    engine.context_budget=36000;engine.usage_log=root/'model-usage.jsonl';engine.calls=state['calls'];engine.usage=state['usage']
    guard=job.get('attribution_guard',False)
    if guard:engine.request_output_limit=3200
    hearing=json.loads(Path(job['hearing']).read_text('utf-8'))
    cache={x['cursor']:x for x in json.loads(Path(job['observation_cache']).read_text('utf-8'))['observations']} if job.get('observation_cache') else {}
    async def ask(prompt,context,parser,stage,frames=None,persona=False):
        feedback=''
        for attempt in range(3):
            content=[{'type':'text','text':json.dumps(context,ensure_ascii=False)}]+(frames or [])
            messages=[{'role':'system','content':(system[0]['content']+'\n' if persona else '')+prompt+feedback},{'role':'user','content':content}]
            if prefix.get('enabled'):messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
            engine.stage=stage;engine.source_cursor=cursor
            raw=''
            try:
                raw=(await engine.complete(messages,key))[0]
                value=parser(raw)
                with (root/'requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'cursor':cursor,'stage':stage,'input':context,'frame_times':[x['text'] for x in frames or [] if x['type']=='text'],'output':value},ensure_ascii=False)+'\n')
                return value
            except (ValueError,KeyError,TypeError) as exc:
                save(root/f'format-{engine.calls}.json',{'stage':stage,'raw':raw,'error':str(exc)})
                if attempt==2:raise
                # Invalid raw output is retained in format-*.json. Reinjecting it
                # duplicates the evidence and can overflow the context on retry.
                feedback='\n上次输出未通过结构校验，请依据同一份输入重新返回完整合法JSON。保持证据边界，不增加发言或风格要求。校验原因：'+str(exc)
            except Exception:
                if attempt==2:raise
                await asyncio.sleep(2)
    while state['cursor']<job['seconds']:
        cursor=min(job['seconds'],state['cursor']+2);state['wall']+=cursor-state['cursor']
        frames=[]
        for index,at in frame_batch(cursor,job['seconds']):
            data=base64.b64encode((Path(job['frames'])/f'{index:06d}.jpg').read_bytes()).decode()
            frames.extend([{'type':'text','text':f'已看到 {at:.2f} 秒'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+data}}])
        # Narrative receives raw evidence, not a prior observer's audit language.
        hearing_context=compact_hearing(recent_heard(heard_until(hearing,cursor)))
        heard=hearing_context['heard_dialogue']
        context={'viewed_through':cursor,'previous_understanding':narrative_state(state['understanding']),**hearing_context}
        if guard:context['utterance_evidence']=recent_utterances(state.get('utterances',{}))
        def parse_scene(raw):
            x=parse_understanding(raw,cursor)
            if guard:update_utterances(state.get('utterances'),x.get('speech_updates'),cursor,heard)
            return x
        if cursor in cache:
            understanding={k:v for k,v in cache[cursor].items() if k!='cursor'}
            parse_understanding(json.dumps(understanding),cursor)
            with (root/'requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'cursor':cursor,'stage':'cached_understanding','cache':job['observation_cache'],'output':understanding},ensure_ascii=False)+'\n')
        else:
            understanding=await ask(UNDERSTAND+('\n'+ATTRIBUTION if guard else ''),context,parse_scene,'understanding',frames)
        if guard:
            state['utterances']=update_utterances(state.get('utterances'),understanding['speech_updates'],cursor,heard)
            understanding['speech_updates']=[state['utterances'][x['id']] for x in understanding['speech_updates']]
        state['observations'].append({'cursor':cursor,**understanding});state['understanding']=understanding
        own=own_space(state['decisions'],state['wall'])
        # Observation cadence is not a speech quota. The actor, not the observer,
        # chooses whether to share; only simultaneous self-speech is excluded.
        if not own['currently_speaking']:
            context=decision_context(understanding,audio_space(hearing,cursor),own,state['attention'],cursor)
            if guard:context['utterance_evidence']=recent_utterances(state['utterances'])
            choice=await ask(DECIDE+('\n'+PUBLIC_EVIDENCE if guard else ''),context,parse_decision,'decision',persona=True)
            if choice['action']=='replay':
                replay=[]
                for index,at in frame_batch(cursor,job['seconds'],choice['replay_seconds']):
                    data=base64.b64encode((Path(job['frames'])/f'{index:06d}.jpg').read_bytes()).decode()
                    replay.extend([{'type':'text','text':f'回看已看到的 {at:.2f} 秒'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+data}}])
                state.setdefault('replays',[]).append({'cursor':cursor,'request':choice})
                understanding=await ask(UNDERSTAND+('\n'+ATTRIBUTION if guard else ''),{**context,'previous_understanding':narrative_state(understanding),**hearing_context},parse_scene,'replay_understanding',replay)
                if guard:state['utterances']=update_utterances(state.get('utterances'),understanding['speech_updates'],cursor,heard)
                state['understanding']=understanding
                context=decision_context(understanding,audio_space(hearing,cursor),own,state['attention'],cursor)
                if guard:context['utterance_evidence']=recent_utterances(state['utterances'])
                choice=await ask(DECIDE+('\n'+PUBLIC_EVIDENCE if guard else ''),context,parse_decision,'replay_decision',persona=True)
            initial=choice
            if choice['action'] in ('speak','pause'):
                context={**context,'proposed':choice,'estimated_voice_seconds':len(choice['text'])/job['voice_chars_per_second'],'duration_is_estimate':True}
                choice=await ask(ARRANGE,context,parse_decision,'listening_arrangement',persona=True)
            checks=[]
            if guard:
                for attempt in range(3):
                    if choice['action'] not in ('speak','pause'):break
                    candidate=choice['text']
                    # Only the final candidate is editable/checkable. Earlier proposals
                    # and already-spoken text must not be mistaken for the current draft.
                    review_context={k:context[k] for k in ('viewed_through','story','cast','utterance_evidence') if k in context}
                    report=await ask(CHECK,{**review_context,'candidate_text':candidate,'heard_dialogue':heard},lambda raw:enforce_bindings(parse_check(raw,candidate),state['utterances'],candidate),'public_fact_check',frames)
                    checks.append({'candidate':choice,'review':report})
                    if not report['issues']:break
                    if attempt==2:
                        # Never silently substitute a fabricated utterance. An unresolved
                        # factual conflict stays blocked in the record, not public speech.
                        state.setdefault('blocked_candidates',[]).append({'cursor':cursor,'choice':choice,'checks':checks})
                        choice={**choice,'action':'continue','text':'','reason':'Candidate not released: factual premise unresolved after actor revisions.'}
                        break
                    choice=await ask(DECIDE+'\n'+PUBLIC_EVIDENCE+'\n'+REVISE,{**context,'candidate':choice,'fact_review':report},parse_decision,'actor_fact_revision',persona=True)
                    if choice['action'] in ('speak','pause'):
                        choice=await ask(ARRANGE,{**context,'proposed':choice,'estimated_voice_seconds':len(choice['text'])/job['voice_chars_per_second']},parse_decision,'revised_listening_arrangement',persona=True)
            duration=len(choice['text'])/job['voice_chars_per_second'] if choice['text'] else 0
            event={'cursor':cursor,'wall':state['wall'],**choice,'initial':initial,'estimated_seconds':duration,'source_audio':context['source_audio'],'own_speech':own,'fact_checks':checks}
            state['decisions'].append(event);state['attention']=choice['attention']
            if choice['action']=='pause':state['wall']+=duration
        state.update(cursor=cursor,calls=engine.calls,usage=engine.usage,prefixEnabled=bool(prefix.get('enabled')),mode='decision_only_no_tts_no_render')
        save(checkpoint,state)
        print(json.dumps({'cursor':cursor,'calls':engine.calls,'decisions':len(state['decisions']),'utterances':sum(e['action'] in ('speak','pause') for e in state['decisions'])}),flush=True)
    state['complete']=True;save(checkpoint,state)
    print('TRACE COMPLETE',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);a=p.parse_args()
    asyncio.run(run(json.loads(a.job.read_text('utf-8-sig'))))
