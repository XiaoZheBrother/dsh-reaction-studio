"""Finalize an explicitly reviewed trace with existing B voice and clock renderer.

Does not invent speech or revise wording. Viewing intent owns playback mode;
measured audio only aligns the timeline and exposes actual execution conflicts.
"""
import argparse
import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from reaction_episode import save
from reaction_events import scene_prefix
from reaction_server import Reactor
from reaction_continuity import parse_json
from reaction_voice import prepare_voice
from reaction_performance import validate_performance
from reaction_pacing import PlaybackTimeline,pause_duration
from live_pilot_chat import generator

PLAYBACK_POLICY='viewing_intent_v1'


def parse_conflict(raw):
    value=parse_json(raw)
    if value.get('action') not in ('wait_while_playing','pause_and_wait') or not isinstance(value.get('reason'),str):
        raise ValueError('Resolve actual overlapping voices with wait_while_playing or pause_and_wait')
    return value


async def main(a):
    job=json.loads(a.job.read_text('utf-8-sig'))
    review=json.loads(a.review.read_text('utf-8'))
    raw=a.trace.read_bytes();trace=json.loads(raw)
    if review.get('status')!='accepted_for_preview' or review.get('trace_sha256')!=hashlib.sha256(raw).hexdigest():
        raise ValueError('Review must match the exact completed trace')
    if not trace.get('complete'):raise ValueError('Viewing incomplete')
    production=json.loads(a.production.read_text('utf-8'))
    settings=production['voice_studio']
    a.output.mkdir(parents=True,exist_ok=True)
    prior_path=a.output/'viewing-state.json'
    prior=json.loads(prior_path.read_text('utf-8')) if prior_path.exists() else {}
    committed_count=len(prior.get('events',[]))
    if committed_count and prior.get('playback_policy')!=PLAYBACK_POLICY:
        raise ValueError('Playback policy changed; use a separate output to preserve the previous timeline')
    for event in prior.get('events',[]):
        original=trace['decisions'][event['id']]
        if event['text']!=original['text'] or event['original_source']!=original['cursor']:
            raise ValueError('Existing dubbing belongs to another trace; use a separate output')
    system,prefix,key=generator.load_context(Path(job['home']),Path(job['persona']),scene='reaction_offline')
    prefix=scene_prefix(prefix,job)
    engine=Reactor(Path(job['home']),Path(job['persona']),max_calls=100)
    engine.context_budget=36000;engine.usage_log=a.output/'model-usage.jsonl'
    async def ask(prompt,context,parser):
        messages=[{'role':'system','content':system[0]['content']+'\n'+prompt},
                  {'role':'user','content':json.dumps(context,ensure_ascii=False)}]
        if prefix.get('enabled'):messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
        raw=(await engine.complete(messages,key))[0]
        return parser(raw)
    state={'playback_policy':PLAYBACK_POLICY,'input':{'seconds':job['seconds']-job['start_seconds']},'events':[],'performances':[],
           'playbacks':[],'pauses':[],'cursor':0,'complete':False,'dubbing':{'provider':'IndexTTS2','prefixEnabled':bool(prefix.get('enabled'))}}
    def persist():
        # Rebuild cached events privately on resume; never move the renderer's
        # committed watermark backwards or reannounce old performances.
        if len(state['events'])<committed_count:return
        # Publish referenced event metadata before the matching clock watermark.
        save(a.output/'decisions.json',{'events':state['events']})
        save(a.output/'clock-metrics.json',{'speed':1,'playbacks':state['playbacks'],'performances':state['performances'],'pauses':state['pauses']})
        save(a.output/'viewing-state.json',state)
    persist()
    voice_until=0
    for index,event in enumerate(trace['decisions']):
        source=event['cursor']-job['start_seconds'];at=PlaybackTimeline(state['pauses']).output_at(source)
        presentation=validate_performance(event.get('performance'))
        item={'id':index,'cursor':source,'original_source':event['cursor'],'text':event['text'],
              'action':event['action'],'performance':presentation,'output_at':at}
        if event['action'] in ('speak','pause'):
            engine.source_cursor=event['cursor'];engine.stage='voice_delivery'
            context={'source_seconds':event['cursor'],'your_chosen_reaction':event['text'],'your_intent':event['reason']}
            prepared=await prepare_voice(event['text'],settings,a.output.parent/'voice-cache',ask,context)
            actual=prepared['duration'];remaining=max(0,voice_until-at)
            receipt=a.output/f'playback-{index}.json'
            mode={'policy':PLAYBACK_POLICY,'mode':'pause' if event['action']=='pause' else 'overlay',
                  'reason':'执行观看时的播放决定','original_action':event['action']}
            if remaining>0.001 and event['action']=='speak':
                engine.stage='playback_conflict'
                conflict_path=a.output/f'conflict-{index}.json'
                conflict_input={**context,'actual_seconds':actual,'previous_voice_remaining':remaining,
                                'previous_voice_end':voice_until,'requested_start':at,'original_mode':event['action']}
                if conflict_path.exists():
                    cached=json.loads(conflict_path.read_text('utf-8'))
                    if cached['input']!=conflict_input:raise ValueError('Cached conflict belongs to another timeline')
                    resolution=parse_conflict(json.dumps(cached['resolution']))
                else:
                    resolution=await ask('观看时你已经选择继续播放原片，这个决定默认保留。现在发生的实际冲突是：你上一句声音还未结束，新一句按原时间开始会与自己的声音重叠。只处理这个执行冲突，不重新评价反应、未知对白或长短；不改文字。选择wait_while_playing：原片继续，等上一句结束再说；或者pause_and_wait：你现在明确决定暂停原片，等上一句结束并说完这句再继续。返回JSON {"action":"wait_while_playing/pause_and_wait","reason":"处理实际冲突的理由"}。',conflict_input,parse_conflict)
                    save(conflict_path,{'input':conflict_input,'resolution':resolution})
                mode.update(mode='pause' if resolution['action']=='pause_and_wait' else 'overlay',reason=resolution['reason'],conflict=resolution)
                if resolution['action']=='wait_while_playing':at+=remaining
            if mode['mode']=='pause':
                state['pauses'].append({'source':source,'duration':pause_duration(remaining+actual),'reason':mode['reason']})
                at+=remaining
            save(receipt,mode)
            path=a.output/f'voice-{index}.wav';shutil.copyfile(prepared['path'],path)
            item.update(audio='/audio/'+path.name,duration=actual,output_at=at,delivery=mode['mode'],
                        captions=prepared['subtitles'])
            voice_until=at+actual
            state['playbacks'].append({'id':index,'wall':at,'source':source,'text':event['text']})
            print(json.dumps({'source':event['cursor'],'duration':actual,'mode':mode['mode']}),flush=True)
        state['events'].append(item)
        state['performances'].append({'wall':at,'source':source,'selected':presentation})
        state['cursor']=source;persist()
    state['complete']=True;persist()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('job','review','trace','production','output'):p.add_argument('--'+k,type=Path,required=True)
    asyncio.run(main(p.parse_args()))
