"""Separate recorded media observations from explicitly supplied viewer events."""
import copy

EVENT_CONTRACT = '''输入是系统投递的事件，不等于搭档发消息。media_observation里的字幕、声音、人物话语以及你的记忆都不是观众消息。真实观众消息只在viewer_messages里；空数组代表当前没有人向你提问。可以自发对影片反应，不需要有人提问才开口。若选择回复真实观众，在reply_to_message_id填写对应id；自发反应或沉默填null。不要为解释自己的反应补写不存在的提问。'''


def envelope(context, cursor, viewer_messages=()):
    return {'event':{'kind':'media_observation','source':'video_player','at':cursor},
            'viewer_messages':copy.deepcopy(list(viewer_messages)),
            'media_observation':context}


def validate_reply(choice, messages):
    target=choice.get('reply_to_message_id')
    if target is not None and target not in {m['id'] for m in messages}:
        raise ValueError('reply_to_message_id must refer to an actual viewer message; spontaneous reaction uses null')
    return choice


def scene_prefix(prefix, job):
    result=copy.deepcopy(prefix)
    override=job.get('reaction_prefix')
    if override is not None:
        if not isinstance(override,str) or not override.strip():raise ValueError('reaction_prefix must be nonempty text')
        result['prefix']=override
    # The existing global switch remains authoritative.
    return result
