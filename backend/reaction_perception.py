"""Evidence extraction is separate from the character's response choice."""
import json

PERCEPTION = '''你负责持续理解一段正在播放的故事。只使用截至cursor的画面、字幕和之前的观察，不使用已知作品资料或未播放内容。
把当前片段放回已经发生的事件中，理解人物、处境、行动和因果。延续仍成立的人物关系和事件，不因切镜头就清空前情；新证据可以修正先前解释。continuity.plot_memory中的episodes是较早的分段记忆，recent是近期完整观察；按时间联系，更新证据可推翻旧解释。recent_events、continuity也可能有误，保留修正的依据。
字幕可能是对白、旁白或内心活动。结合连续画面、文字的人称、视点和语境推断归属；明确的证据与合理推断分开，不要求每句都出现可见口型。证据不足时保留真正影响剧情理解的疑问，不把所有未拍出的动作都当作剧情疑点。
输出JSON对象，字段都是中文字符串：visual(这一段人物具体做了什么，最多300字)、dialogue(关键字幕及其可能归属，区分已知与推断，最多300字)、story(从开头到当前仍重要的经历、关系、因果及当前处境，最多1200字，不是仅复述最后一个镜头)、uncertain(影响理解而尚未解决的问题，最多300字)、event(本轮新增信息，最多250字)、correction(旧解释如何被新证据修正，没有则空，最多300字)。不代替角色写回应，不评价剪辑技术，不预告剧情。'''



def parse_perception(raw):
    value = json.loads(raw)
    result = {}
    for name, limit in [('visual',300), ('dialogue',300), ('story',1200), ('uncertain',300), ('event',250), ('correction',300)]:
        text = value.get(name) if isinstance(value, dict) else None
        if not isinstance(text, str) or len(text) > limit:
            raise ValueError('观察证据字段不完整或过长')
        result[name] = text
    return result
