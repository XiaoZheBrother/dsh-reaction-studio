"""Evidence-scoped utterance attribution, separate from narrative identity."""
import copy,math
from reaction_continuity import parse_json

ATTRIBUTION = '''额外保存 speech_updates：台词的“内容、叙述方式、归属”分开判断。字幕出现时画面中的人不自动等于说话者；第一人称叙事、反问、自述可能属于内心独白、画外旁白或画内对白。人物对声音没有回应不单独证明它是独白，口型画面也不单独证明音画同步。判断要综合连续视角、上下句回应、称呼、口部运动与已提供听觉证据。
当前输入只有图像序列、ASR文字和不可靠的匿名声音簇，没有直接听音色或验证音画口型同步的能力。不可声称听出了语气/声线归属或验证了lip-sync。原片字幕可以作为文字证据，但字幕内容本身不能证明具体画内人物在说。叙事中“我”的连续性可以作为working理解，不需要先认出声纹；它与台词是否说出声是两个判断。
speech_updates必须为数组，每次只提交新增/修订的台词（最多6条）：{id:"稳定台词id",text:"原句或忠实摘录",at:数字秒数,source:"subtitle/audio",cue_id:"audio时为输入真实id，否则null",mode:"spoken/inner/narration/unknown",mode_status:"working/confirmed/unknown",speaker:"人物id或null",speaker_status:"working/confirmed/unknown",evidence:["subtitle_text/visual_presence/visible_mouth_movement/discourse_continuity/explicit_address/reciprocal_response/self_identification"],reason:"支持、替代解释与修改理由"}。
仅画面出现或嘴动不能确认台词归属。有互相回应/明确称呼/自我指认也必须说明如何支持，不能凭空添加证据标签。没有可用证据时保持unknown。若speaker为working，story不能把“某某亲口说了某句话”写成事实；可以理解为叙述者的自述或尚未归属的台词。修订归属时同步修正依赖它的人物状态/关系；旧记录保留，不把旧猜测反复当新证据。'''

PUBLIC_EVIDENCE = '''utterance_evidence分别标注台词内容、说出方式、人物归属。人物身份的工作解释不能升级为“这个人亲口说过”的事实。你可以回应一句话本身、已有行动或自己的感受；不必向观众汇报所有未知，也不需要固定加“可能/我猜”。若你的吐槽依赖某人确实说过/做过某事，先看这个前提是否成立；不成立时由你决定换个想法、回看或不说。'''

CHECK = '''任务是辨别原话是否真的做了具体的事实断言，不是尽量找错。不评价有趣程度、语气、长短或是否应该发言，不代写台词。
先做语义分类：主观感受、找人/好奇的意愿、比喻、自嘲、提问不自动等于具体事实断言；只有确实蕴含“某个具体角色说了X/做了X/具有某身份”的内容才进入归属核对。泛指尚未知身份的“说话者”不等于替它认定了身份。不要凭空添加原话没有断言的命题。
通用边界示例（不是推荐台词）：原句“我都找晕了，说话的人在哪”没有把任何具体画面人物认作说话者，应通过；原句“窗边那位刚说要走，怎么又坐下”实际断言窗边人说过要走，若归属未知，应指出这项前提。
根据截至viewed_through的画面、对白、台词归属记录，查找原话是否把working/unknown身份、内心独白、比喻或画外话语当成某个画内人物实际说过/做过的确定事实；也检查原话是否基于错误的字面解读。不能因为此前摘要写过就当真，摘要是待核对的推断。主观感受和明确提出的猜想不是事实错误，但用问句包装一个断言（“你刚才不是说过…吗”）仍有事实前提。
按日常语境理解比喻、夸张、自嘲和主观比较，不把它们强行解释成字面上的存在性或心理诊断断言。仅当反应确实依赖一个具体人物做了/说了某事、身份或剧情关系为真的前提时，才因归属证据不足提出问题。不要把“缺少所有细节的证据”当成“不允许有感受”。不要要求为每一句补免责声明，不把无关未知报出来。
另外必须提取 bindings 数组：对原话中每个把台词绑定给具体人物、或明确认定说出方式的语义命题，返回{quote:"准确子串",utterance_id:"utterance_evidence里的id，不知道则null",kind:"speaker/mode",asserted_as_fact:true或false,value:"人物id或mode值"}。这里只提取原话实际说了什么，不判断它是否有证据。提问包着确定前提也属于asserted_as_fact=true，明确保留的猜想才为false。泛指尚未认人的叙述者/说话者，不算具体speaker绑定。
例如“窗边那位张嘴就在问谁来了”是speaker事实绑定，即使画面确实张嘴，也要提取；证据是否足够由独立规则检查，不能由你升级working状态。普通比喻、感受不进入bindings。
只返回JSON {"issues":[{"quote":"原话中准确的子串","assertion":"原话实际断言的具体人物+言行/身份，不额外推导","reason":"这个具体前提缺乏什么证据或与什么冲突"}],"bindings":[...]}；无法指出这类具体断言或证据支持时issues为空。你没有原声音频，不能凭空断言谁的声线或语气。'''

REVISE = '''这是你拟说的话的独立事实核对，只指出缺证据的前提，没有替你改文风。你自己决定改说法、换关注、回看或继续观看不说；不得仍把所指出的未知归属当确定事实。无需为每处未知加固定口头禅。保持自己的想法和表达。
请按现有决策格式返回完整JSON。核查意见不是对外台词，也不是观众提出的问题。'''

def update_utterances(previous,updates,cursor,heard):
    if not isinstance(updates,list) or len(updates)>6:raise ValueError('speech_updates must be array with at most 6 changes')
    result=copy.deepcopy(previous or {})
    ids={x['id'] for x in heard}
    for raw in updates:
        row=copy.deepcopy(raw)
        if not isinstance(row.get('id'),str) or not row['id'] or not isinstance(row.get('text'),str):raise ValueError('utterance identity/text')
        at=row.get('at')
        if type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<=cursor:raise ValueError('utterance at must be a past numeric second')
        if row.get('source') not in ('subtitle','audio'):raise ValueError('utterance source')
        if row['source']=='audio' and row.get('cue_id') not in ids:raise ValueError('unheard audio cue')
        if row.get('mode') not in ('spoken','inner','narration','unknown'):raise ValueError('utterance mode')
        for k in ('mode_status','speaker_status'):
            if row.get(k) not in ('working','confirmed','unknown'):raise ValueError('utterance certainty')
        evidence=row.get('evidence',[])
        allowed={'subtitle_text','visual_presence','visible_mouth_movement','discourse_continuity','explicit_address','reciprocal_response','self_identification'}
        if not isinstance(evidence,list) or any(x not in allowed for x in evidence):raise ValueError('unsupported evidence type; raw voice/lip synchronization was not provided')
        if row.get('speaker') and row['speaker_status']=='confirmed' and not set(evidence)&{'explicit_address','reciprocal_response','self_identification'}:
            row['speaker_status']='working';row['validation_note']='Visible presence, mouth movement and continuity do not independently confirm speaker identity.'
        if not row.get('speaker'):row['speaker_status']='unknown'
        if row['mode']=='unknown':row['mode_status']='unknown'
        old=result.get(row['id']);row['revision']=1 if old is None else old['revision']+1
        row['updated_at']=cursor
        if old:row['prior']={k:v for k,v in old.items() if k!='prior'}
        result[row['id']]=row
    return result

def recent_utterances(ledger):
    return [{k:v for k,v in row.items() if k!='prior'} for row in sorted(ledger.values(),key=lambda x:x['updated_at'],reverse=True)[:12]]

def parse_check(raw,text):
    x=parse_json(raw)
    if not isinstance(x.get('issues'),list):raise ValueError('issues array required')
    for item in x['issues']:
        if not isinstance(item.get('quote'),str) or not item['quote'] or item['quote'] not in text:raise ValueError('quote must be exact substring of candidate speech')
        if not isinstance(item.get('reason'),str) or not item['reason']:raise ValueError('issue reason required')
    return x

def enforce_bindings(report,ledger,text):
    """A checker cannot promote an uncertain speaker merely by agreeing with it."""
    report=copy.deepcopy(report)
    if not isinstance(report.get('bindings'),list):raise ValueError('bindings array required; extract concrete speaker/mode assertions even when issues is empty')
    for b in report['bindings']:
        if not isinstance(b.get('quote'),str) or not b['quote'] or b['quote'] not in text:raise ValueError('binding quote must occur in candidate')
        if b.get('kind') not in ('speaker','mode') or type(b.get('asserted_as_fact')) is not bool:raise ValueError('binding kind/certainty required')
        if not b['asserted_as_fact']:continue
        row=ledger.get(b.get('utterance_id'))
        kind=b['kind']
        if not row or row.get(kind+'_status')!='confirmed' or row.get(kind)!=b.get('value'):
            report['issues'].append({'quote':b['quote'],'assertion':kind+' attribution','reason':'This exact attribution is not confirmed in the evidence ledger; visible mouth movement or checker agreement cannot promote it.','enforced':True})
    return report
