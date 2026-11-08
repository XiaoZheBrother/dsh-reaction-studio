"""Bounded playback tools for the offline viewer, independent of model/provider.

Calls are model-selected JSON tool envelopes. The host supplies the observed
cursor and measured audio duration: a model cannot seek unseen footage, choose
file paths, or create arbitrary wall-clock delays. Receipts live in the job only.
"""
from reaction_pacing import pause_duration, PlaybackTimeline

TOOLS = [
    {'name':'reaction_pause','description':'暂停当前已看位置，展开这次讨论；语音结束即释放暂停。仅在值得打断观看时使用。',
     'arguments':{'reason':'为什么值得暂停','resume':'speech_end'}},
    {'name':'reaction_continue','description':'继续正常播放，可边看边说；不要求一定说话。','arguments':{}},
    {'name':'reaction_replay','description':'回看已看过的一段；不能获取未来剧情。','arguments':{'seconds':'1至10秒'}},
]


def execute_playback_tool(state, call, *, call_id, cursor, speech_duration=0):
    receipts=state.setdefault('tool_receipts',[])
    old=next((r for r in receipts if r['call_id']==call_id),None)
    if old:
        if old['call']!=call or old['source']!=cursor:
            raise ValueError('Tool id reused for different operation')
        return old['result']
    name=call.get('name');args=call.get('arguments',{})
    if not isinstance(args,dict):raise ValueError('Invalid tool arguments')
    if not 0<=cursor<=state['input']['seconds']:raise ValueError('Tool cursor outside source')
    if name=='reaction_pause':
        if set(args)!={'reason','resume'} or args['resume']!='speech_end':
            raise ValueError('Pause must release at speech end')
        if not isinstance(args['reason'],str) or not args['reason'].strip() or not 0<speech_duration<3600:
            raise ValueError('Pause requires reason and measured speech')
        pauses=state.setdefault('pauses',[])
        hold={'id':call_id,'source':cursor,'duration':pause_duration(speech_duration),'reason':args['reason']}
        PlaybackTimeline(pauses+[hold])
        begin=PlaybackTimeline(pauses).output_at(cursor)
        pauses.append(hold)
        result={'paused_at':cursor,'output_start':begin,'output_resume':begin+hold['duration'],
                'resume_at_source':cursor,'release':'speech_end'}
    elif name=='reaction_continue':
        if args:raise ValueError('Continue takes no arguments')
        result={'source':cursor,'playing':True}
    elif name=='reaction_replay':
        seconds=args.get('seconds')
        if set(args)!={'seconds'} or isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 1<=seconds<=10:
            raise ValueError('Invalid replay range')
        result={'from':max(0,cursor-seconds),'through':cursor,'future_frames':False}
    else:raise ValueError('Unknown playback tool')
    receipts.append({'call_id':call_id,'source':cursor,'call':call,'result':result})
    return result
