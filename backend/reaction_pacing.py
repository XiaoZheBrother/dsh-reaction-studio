"""Editorial choices belong to the viewer; the timeline only executes them."""
import json
import math
import subprocess

PACING_PROMPT = '''你在与人一起看动画，不是向人解说画面或交付分析报告。默认接着看；沉默也是正常的陪伴。有反应时，说眼前最想脱口而出的那一点即可，不必附带画面复述、论证和总结。不模仿固定口头禅，不按频率凑发言。
只有你确实想当场讨论一个值得展开的问题时才选择暂停；不要为了容纳一段冗长台词而暂停。也可以把完整理解留到片尾。不预设情绪，也不要求每次都简短到固定字数。
若选择speak，同时给delivery：overlay表示边看边说，pause表示暂停动漫展开，pause_reason说明为什么值得打断观看（overlay时为空）。你可以保留疑问继续看，不必立刻分析出答案。'''

SPEECH_PROMPT = '''你已决定开口。这是陪看时的反应，不是画面解说、内容梗概或写稿。按自己选的意图直接说想说的那一点，不必把内部剧情理解、证据、分析和结论都讲出来。若选了暂停讨论，可以围绕那个问题展开。只输出实际说出口的话，不念动作指令。没有原声音频输入，不臆测音色。'''

REVIEW_PROMPT = '''这是你自己的台词试听前检查，不是观众的新问题。已给出实际合成时长，请判断这段话是否值得占用这么久。
你自主选择keep（原样边看边说）、shorten（自己重新说得简短直接）、pause（确有值得当场展开的问题，暂停聊）、defer（此刻不说，留到片尾或放下）。不能仅因台词长就选pause。没有固定秒数或字数门槛。不添加新剧情，不代替自己决定情绪。
只返回JSON：{"choice":"keep/shorten/pause/defer","reason":"理由","text":"shorten时的新台词，否则空"}。'''


def parse_review(raw):
    decoder = json.JSONDecoder()
    values = []
    calls = []
    for i, char in enumerate(raw):
        if char != '{':
            continue
        try:
            item, _ = decoder.raw_decode(raw[i:])
            if isinstance(item,dict) and item.get('name') in ('reaction_continue','reaction_pause'):
                calls.append(item)
            if item.get('choice') not in ('keep', 'shorten', 'pause', 'defer'):
                continue
            if not isinstance(item.get('reason'), str) or not item['reason'].strip():
                continue
            if item['choice'] == 'shorten' and not (isinstance(item.get('text'), str) and item['text'].strip()):
                continue
            call=item.get('tool_call')
            if call is not None:
                expected={'keep':'reaction_continue','pause':'reaction_pause'}.get(item['choice'])
                if not isinstance(call,dict) or call.get('name')!=expected:
                    continue
                args=call.get('arguments')
                if not isinstance(args,dict):continue
                if expected=='reaction_continue' and args:continue
                if expected=='reaction_pause' and (set(args)!={'reason','resume'} or args['resume']!='speech_end' or not isinstance(args['reason'],str) or not args['reason'].strip()):continue
            values.append(item)
        except (ValueError, AttributeError):
            pass
    if len(values) != 1:
        raise ValueError('Expected one pacing decision with reason')
    # Some prefix-capable providers emit the selected tool as a second JSON
    # object. Preserve that explicit call; never silently ignore or invent it.
    if 'tool_call' not in values[0] and calls:
        if len(calls)!=1:raise ValueError('Expected one playback tool call')
        values[0]['tool_call']=calls[0]
        return parse_review(json.dumps(values[0],ensure_ascii=False))
    return values[0]


def pause_duration(duration, fps=24):
    return math.ceil(duration * fps) / fps


class PlaybackTimeline:
    """Source and composition clocks separate only at explicit actor-owned pauses."""
    def __init__(self, pauses=()):
        self.pauses = sorted(pauses, key=lambda p: p['source'])
        last = -1
        for p in self.pauses:
            if not all(isinstance(p.get(k), (int, float)) and math.isfinite(p[k]) for k in ('source', 'duration')):
                raise ValueError('Invalid pause')
            if p['source'] < 0 or p['source'] <= last or p['duration'] <= 0:
                raise ValueError('Invalid or duplicate pause')
            last = p['source']

    def output_at(self, source, after=True):
        return source + sum(p['duration'] for p in self.pauses if p['source'] < source or (after and p['source'] == source))

    def source_at(self, output):
        offset = 0
        for p in self.pauses:
            start = p['source'] + offset
            if output < start:
                break
            if output < start + p['duration']:
                return p['source']
            offset += p['duration']
        return max(0, output - offset)


def source_audio(ff, video, output, start, seconds, pauses):
    """Insert silence at holds; resume the exact next sample at unity gain.

    Stream PCM to disk rather than building per-pause filter branches or retaining
    the entire movie in memory. The shared source clock also selects video frames.
    """
    timeline = PlaybackTimeline(pauses)
    rate = 48000
    raw = output.with_suffix('.source.f32le')
    subprocess.run([ff, '-v', 'error', '-y', '-ss', str(start), '-i', str(video),
                    '-t', str(seconds), '-vn', '-ar', str(rate), '-ac', '2', '-f', 'f32le', str(raw)], check=True)
    with raw.open('rb') as source, output.open('wb') as dest:
        position = 0
        def copy_samples(n):
            nonlocal position
            while n > 0:
                size = min(n, rate)
                block = source.read(size * 8)
                dest.write(block + bytes(size * 8 - len(block)))
                position += size
                n -= size
        for p in timeline.pauses:
            if p['source'] > seconds:
                raise ValueError('Pause beyond source')
            target = round(p['source'] * rate)
            copy_samples(target - position)
            remaining = round(p['duration'] * rate)
            while remaining:
                size = min(remaining, rate)
                dest.write(bytes(size * 8))
                remaining -= size
        copy_samples(round(seconds * rate) - position)
    raw.unlink()
    return output
