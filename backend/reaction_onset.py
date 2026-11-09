"""Plan an opening from evidence already seen, not from model/network elapsed time."""
import base64,json
from pathlib import Path
from reaction_timing import validate_timing
from reaction_pacing import PlaybackTimeline

async def choose_onset(event,original,viewing,ask,voice_until,pauses):
    cursor=event['cursor'];end=original['input']['seconds']
    content={'observed_through':cursor,'evidence_ready_at':cursor,'story':event.get('story'),'observation':event.get('observation'),
             'your_text':event.get('text'),'chosen_delivery':event.get('delivery'),'actual_voice_seconds':event.get('duration'),
             'previous_voice_until_output':voice_until,'existing_pauses':pauses,
             'note':'只提供当时已经看过的内容。后面的剧情尚不可用。所给时长是配音长度，不能当作已等待时长。'}
    content['valid_time_range']={'understood_at_min':cursor,'speak_at_max':end,'order':'understood_at < speak_at; both are absolute source seconds, not delay amounts'}
    if original['input'].get('hearing'):
        from reaction_attention import heard_until
        hearing=json.loads(Path(original['input']['hearing']).read_text('utf-8'))
        content['timestamped_hearing']=heard_until(hearing,cursor)[-8:]
    frames=[]
    for t in event.get('frames',[])[-8:]:
        if t>cursor:raise ValueError('Future frame in timing evidence')
        path=Path(viewing)/'observed-frames'/f'{round(t*4)+1:06d}.jpg'
        if path.exists():frames.extend([{'type':'text','text':f'已看画面 {t:.2f} 秒'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()}}])
    def parse(raw):
        value,_=json.JSONDecoder().raw_decode(raw[raw.index('{'):])
        if value.get('choice')=='defer' and isinstance(value.get('reason'),str):return value
        if value.get('choice')!='speak':raise ValueError('Choose speak or defer')
        result=validate_timing(value,evidence_ready=cursor,considered_at=cursor,source_end=end)
        if PlaybackTimeline(pauses).output_at(result['speak_at'])<voice_until:raise ValueError('Choose an opening after your previous utterance finishes, or defer')
        return result
    return await ask('你已经选择了这句反应，现在决定自然开口的时机。观察时刻不是开口时刻。判断这次要读懂字幕、听完已收到的对白、理解反差需要怎样的停顿；简短惊叹和需要联系上下文的吐槽可以不同。不预设固定一秒，也不采用模型请求的耗时。understood_at 是理解完成时刻，不是首次看见字幕；speak_at 是开始说话的源视频秒数，必须晚于理解完成，并且不超过本片段结束。若此刻不值得说、需要更多信息或没合适的开口时机，可以defer取消。只返回JSON {"choice":"speak/defer","understood_at":数字,"speak_at":数字,"reason":"这一处这样选择的原因"}。不要改台词或猜后续。',{'evidence':content,'source_end':end,'_frames':frames},parse)
