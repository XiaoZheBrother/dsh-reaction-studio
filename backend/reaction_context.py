"""Bounded working context; estimates are not a provider tokenizer."""
import json
import math
import copy


def text_cost(value):
    # Conservative UTF-8 byte bound for text; images use a separate estimate.
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8')) + 32


def pack_decision(system, prefix, payload, budget=24000):
    data = copy.deepcopy(payload)
    omitted = 0
    events_omitted = 0
    while True:
        messages = copy.deepcopy(system) + [{'role':'user','content':json.dumps(data,ensure_ascii=False)}]
        if prefix.get('enabled'):
            messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
        estimate = text_cost(messages)
        if estimate + 1800 <= budget:
            return messages, {'estimatedInput':estimate,'inputLimit':budget-1800,'spokenOmitted':omitted,'eventsOmitted':events_omitted}
        spoken = data.get('playback', {}).get('spoken', [])
        if isinstance(spoken, list) and spoken:
            spoken.pop(0)
            omitted += 1
            continue
        events = data.get('observed_history', [])
        if events:
            events.pop(0)
            events_omitted += 1
            data['history_omitted'] = events_omitted
            continue
        raise ValueError('回应必要上下文超出预算，观察记录已保留')


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
