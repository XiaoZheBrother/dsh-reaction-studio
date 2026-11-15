"""Bounded working context; estimates are not a provider tokenizer."""
import json
import math
import copy
from reaction_memory_selection import select_optional_memories, current_query

# Optional history only. Persona, prefix, current evidence and chosen speech are
# never shortened to make a request fit. Files remain the complete source.
OPTIONAL_HISTORY = {'recent_observations', 'since_last_deliberation', 'records',
                    'chronological_observations', 'observed_history', 'memory', 'spoken',
                    'your_reactions_from_this_run'}

def summary_batch(events, byte_budget=10000):
    """Consume a contiguous prefix only, so summary receipts never overclaim."""
    selected=[];used=0
    for event in events:
        cost=text_cost({k:event.get(k) for k in ('cursor','story','interest')})
        if used+cost>byte_budget:break
        selected.append(event);used+=cost
    if events and not selected:raise ValueError('Single observation exceeds summary budget')
    return selected

def compact_observation(value):
    if not isinstance(value, dict):return value
    return {k:copy.deepcopy(value[k]) for k in
            ('unit_id','boundary','unexpected_change','understanding','change','attributions') if k in value}

def pack_messages(messages, budget=24000, output_reserve=3000):
    """Common bounded request projection; no provider call or persistent mutation."""
    result=copy.deepcopy(messages); payloads=[]; omitted={};system_memories=[]
    memory_marker='以下是只读记忆资料；写稿要求和写稿表达偏好不在本场景加载：\n'
    for m in result:
        if m.get('role')=='system' and isinstance(m.get('content'),str) and memory_marker in m['content']:
            head,tail=m['content'].split(memory_marker,1)
            try:obj,end=json.JSONDecoder().raw_decode(tail)
            except ValueError:continue
            if isinstance(obj,dict) and isinstance(obj.get('memory'),list):
                block={'text':''};payloads.append((block,obj))
                system_memories.append((m,head+memory_marker,block,tail[end:]))
        if m.get('role')!='user':continue
        blocks=m.get('content')
        if isinstance(blocks,str):blocks=[{'type':'text','text':blocks}];m['content']=blocks
        if not isinstance(blocks,list):continue
        for block in blocks:
            if block.get('type')!='text':continue
            try:obj=json.loads(block['text'])
            except (ValueError,TypeError):continue
            if isinstance(obj,dict):payloads.append((block,obj))
    def project(obj):
        if not isinstance(obj,dict):return
        if isinstance(obj.get('hearing'),list) and isinstance(obj.get('speaker_hypotheses'),dict):
            voices={c.get('speaker_id') for c in obj['hearing']}
            obj['speaker_hypotheses']={k:v for k,v in obj['speaker_hypotheses'].items() if k in voices}
        for k,v in list(obj.items()):
            if k in ('previous_unit','observation','accumulated_observation'):obj[k]=compact_observation(v)
            elif k=='hearing' and isinstance(v,list):
                # Cue timestamps and uncertainty stay; per-word copies remain
                # on disk for timing alignment and replay, not every observation.
                obj[k]=[{name:copy.deepcopy(value) for name,value in cue.items() if name!='words'} for cue in v]
            elif k in ('recent_observations','since_last_deliberation') and isinstance(v,list):
                obj[k]=[compact_observation(x) for x in v]
            elif isinstance(v,dict):project(v)
    duplicates=select_optional_memories([obj for _,obj in payloads],current_query(result))
    if duplicates:omitted['duplicate_memory']=duplicates
    for _,obj in payloads:project(obj)
    def estimate():
        for block,obj in payloads:block['text']=json.dumps(obj,ensure_ascii=False)
        for message,head,block,tail in system_memories:message['content']=head+block['text']+tail
        total=0
        for m in result:
            c=m.get('content')
            if isinstance(c,list):
                total+=text_cost({k:v for k,v in m.items() if k!='content'})
                total+=sum(1024 if b.get('type')=='image_url' else text_cost(b) for b in c)
            else:total+=text_cost(m)
        return total
    before=estimate();limit=budget-output_reserve
    def candidates(obj,path=''):
        if not isinstance(obj,dict):return
        for k,v in obj.items():
            if k=='recent' and path.endswith('own_speech.') and isinstance(v,list):
                # Completed older speech remains on disk. Keep the latest
                # utterance and all still-playing speech intact.
                if len(v)>1 and v[0].get('remaining',0)==0:
                    yield path+k,v
            elif k in OPTIONAL_HISTORY and isinstance(v,list) and v:
                yield path+k,v
            elif k=='speaker_hypotheses' and isinstance(v,dict):
                for voice,items in v.items():
                    if isinstance(items,list) and items:yield path+k+'.'+voice,items
            elif isinstance(v,dict):yield from candidates(v,path+k+'.')
    while estimate()>limit-256:
        choices=[item for _,obj in payloads for item in candidates(obj)]
        if not choices:raise ValueError(f'Required context exceeds budget ({estimate()} estimated units, limit {limit}); persona, prefix and current evidence preserved')
        # Drop unrelated voice history and older duplicate observations before
        # the working understanding that carries relationships across scenes.
        name,items=max(choices,key=lambda item:(
            4 if item[0]=='memory' and len(item[1])>2 else
            3 if 'speaker_hypotheses.' in item[0] and len(item[1])>1 else
            2 if 'observations' in item[0] and len(item[1])>2 else
            1 if item[0].endswith('records') and len(item[1])>4 else 0,
            text_cost(item[1])))
        # records snapshots are newest first; other histories are chronological.
        items.pop(-1 if name.endswith('records') else 0)
        omitted[name]=omitted.get(name,0)+1
    # Expose omission to the actor without adding a speaking instruction.
    if omitted:
        note={'type':'text','text':'Context contains selected history only; omitted details remain in the saved viewing record. Use replay when needed; missing evidence is not proof of absence.'}
        user=next((m for m in reversed(result) if m.get('role')=='user'),None)
        if user is not None:user['content'].append(note)
        # A small fixed margin is included by the caller's reserve.
    return result,{'estimated_input':estimate(),'input_limit':limit,'projected_before_budget':before,'omitted':omitted,'estimate_only':True}


def text_cost(value):
    # Conservative UTF-8 byte bound for text; images use a separate estimate.
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8')) + 32


def pack_decision(system, prefix, payload, budget=24000):
    messages=copy.deepcopy(system)+[{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    if prefix.get('enabled'):
        messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
    packed,report=pack_messages(messages,budget=budget,output_reserve=1800)
    # Preserve this API's JSON string contract for its structured decision caller.
    for message in packed:
        if message.get('role')=='user' and isinstance(message.get('content'),list):
            blocks=message['content']
            data=json.loads(blocks[0]['text'])
            if len(blocks)>1:data['context_note']=blocks[1]['text']
            message['content']=json.dumps(data,ensure_ascii=False)
    omitted=report['omitted']
    return packed, {'estimatedInput':report['estimated_input'],'inputLimit':report['input_limit'],
                    'spokenOmitted':omitted.get('playback.spoken',0),'eventsOmitted':omitted.get('observed_history',0),
                    'memoryOmitted':omitted.get('memory',0),'duplicateMemory':omitted.get('duplicate_memory',0)}


def pack_context(system, prefix, body, story, history, budget=24000, scale=1.0):
    limit = budget - 3000  # Reserve observation generation separately.
    payload = {'cursor': body['cursor'], 'question': body.get('question', ''),
               'continuity': story, 'playback': copy.deepcopy(body.get('playback', {})),
               'audio': '未读取原声；字幕不代表语气、音乐或音效。',
               'recent_events': [], 'subtitles': []}
    base = 256 + text_cost(system) + text_cost(prefix) + text_cost(payload)
    image_cost = math.ceil(1024 * max(1.0, scale))
    spoken = payload['playback'].get('spoken', [])
    trimmed_spoken = 0
    while base + image_cost > limit and isinstance(spoken, list) and spoken:
        spoken.pop(0)
        trimmed_spoken += 1
        base = 256 + text_cost(system) + text_cost(prefix) + text_cost(payload)
    if base + image_cost > limit:
        raise ValueError('必要上下文已超出本轮预算，未发送请求')
    frames = [body['frames'][-1]]
    used = base + image_cost
    # Current subtitles before older recollections. Keep entire records.
    for cue in reversed(body.get('cues', [])):
        cost = text_cost(cue)
        if used + cost <= limit:
            payload['subtitles'].insert(0, cue); used += cost
    # Preserve temporal visual evidence before old textual recollections.
    for frame in reversed(body['frames'][:-1]):
        if used + image_cost <= limit:
            frames.insert(0, frame); used += image_cost
    for event in reversed(history):
        cost = text_cost(event)
        if used + cost <= limit:
            payload['recent_events'].insert(0, event); used += cost
        else:
            break
    omitted = len(history) - len(payload['recent_events'])
    payload['context_note'] = f'较早的{omitted}条细节已由continuity滚动概要承接；概要是可修正的理解，不是原始证据。'
    return payload, frames, {'estimatedInput': used, 'inputLimit': limit,
                            'recentKept': len(payload['recent_events']), 'olderOmitted': omitted,
                            'spokenOmitted': trimmed_spoken,
                            'framesKept': len(frames), 'estimateOnly': True}
