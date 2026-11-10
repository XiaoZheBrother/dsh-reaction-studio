"""Domain-neutral, revisioned understanding; separate private evidence and expression."""
import copy, math

STATE_PROMPT='''另外输出updates数组，维护连续理解，不把每次观察重新写成一段解说。每项为{id:稳定标识,kind:entity/relation/event/question/expectation,claim:当前理解,status:tentative/confirmed/revised/rejected/open/resolved,confidence:0至1,evidence_at:[本次已看到的时间点]}。实体未知姓名时用稳定临时标识，认出后更新同一id。关系、问题及预期可被后续证据修正；修正不抹去旧记录。只有输入证据支持才confirmed；不确定说话人不意味着其他已成立的关系也未知。无变化时updates为空。不决定情绪或台词。'''
CHOICE_PROMPT='''你在连续经历这些事情。理解记录是内部参考，不是要向观众汇报的清单。结合自己此前关注的事情、当前变化和刚说过的话，自行决定继续看、开口或回看；无需证明每次观察值得说。不要把内部核对过程自动当作发言主题。若开口，自选delivery=overlay或pause：前者继续播放，后者暂停播放、说完继续；pause_reason记录你的理由。两者都可用，不预设默认偏好，不设频率、字数或情绪目标。'''
EXPRESSION_PROMPT='''你刚决定说话。这里是你关注的事、此刻经历和自己想说的内容。直接表达自己想表达的，不承担交付观察报告、解释依据或组织完整论证的任务。内容和长短由你决定，不添加没看到的剧情。只输出要说出来的话，动作另行记录。'''
ARRANGE_PROMPT='''只安排已经生成的语音怎样播放，不进行文风评分或例行润色。提供的constraints是技术冲突；没有冲突时保留原话和你原选的播放方式。有冲突时由你选择keep（保持原话并选择稍后开口）、pause（暂停原片说完继续）、defer（放下）、shorten（自己重新表达以解决冲突）。不能让两段语音重叠。只返回JSON {"choice":"keep/pause/defer/shorten","reason":"播放安排依据","text":"只有重新表达时填写"}。'''

def apply_updates(previous, updates, cursor):
    if not isinstance(updates,list) or len(updates)>24:raise ValueError('Invalid understanding updates')
    state=copy.deepcopy(previous or {'records':{},'history':[]})
    for u in updates:
        if not isinstance(u,dict) or not isinstance(u.get('id'),str) or not 0<len(u['id'])<=80:raise ValueError('Stable record id required')
        if u.get('kind') not in ('entity','relation','event','question','expectation') or u.get('status') not in ('tentative','confirmed','revised','rejected','open','resolved'):raise ValueError('Invalid record type/status')
        if not isinstance(u.get('claim'),str) or not 0<len(u['claim'])<=1200:raise ValueError('Invalid claim')
        confidence=u.get('confidence')
        if type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:raise ValueError('Invalid confidence')
        times=u.get('evidence_at')
        if not isinstance(times,list) or not times or any(type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=cursor for t in times):raise ValueError('Evidence exceeds viewed range')
        old=state['records'].get(u['id'])
        if old and old['kind']!=u['kind']:raise ValueError('Do not change stable record kind')
        new={**u,'updated_at':cursor,'revision':old['revision']+1 if old else 1}
        state['history'].append({'at':cursor,'before':old,'after':new});state['records'][u['id']]=new
    return state

def snapshot(state):
    records=list((state or {}).get('records',{}).values())
    recent=sorted(records,key=lambda x:x['updated_at'],reverse=True)[:24]
    return {'records':recent,'omitted':max(0,len(records)-len(recent)),'note':'Working hypotheses, not verified facts; earlier revisions remain in the local record.'}

def expression_context(state, event, awareness):
    return {'viewed_through':event['cursor'],'current_experience':event.get('story'),
            'your_attention':state.get('actor_attention',''),'your_intention':event.get('topic'),
            'playback_choice':event.get('delivery'),'pause_reason':event.get('pause_reason'),
            'recent_speech':awareness,'understanding':snapshot(state.get('experience_state'))}

def playback_constraints(onset,duration,previous_end,source_end,delivery='overlay'):
    """All timestamps use the output clock; pauses do not consume source time."""
    return {'overlap_seconds':max(0,previous_end-onset),'beyond_source_seconds':0 if delivery=='pause' else max(0,onset+duration-source_end)}
