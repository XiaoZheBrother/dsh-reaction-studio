"""An episode-end reflection authored by the character from her viewing evidence."""
import argparse,asyncio,base64,json,subprocess
from pathlib import Path
import edge_tts,imageio_ffmpeg
from reaction_server import Reactor
from live_pilot_chat import generator
from reaction_episode import save,performance,nonempty_response
from reaction_frame_render import pcm_audio
from reaction_render import caption_pages
from reaction_performance import PERFORMANCE_PROMPT

async def main(a):
    a.output.mkdir(parents=True,exist_ok=True)
    state=json.loads((a.viewing/'viewing-state.json').read_text(encoding='utf-8'))
    assert state.get('complete')
    end=state['input']['seconds'];last=max(0,end-.25)
    system,prefix,key=generator.load_context(a.home,a.persona,scene='reaction_offline')
    engine=Reactor(a.home,a.persona)
    async def call(content,extra=''):
        messages=[{'role':'system','content':system[0]['content']+'\n'+extra},{'role':'user','content':content}]
        if prefix.get('enabled'):messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
        async def request():return (await engine.complete(messages,key))[0]
        return await nonempty_response(request)
    def obj(raw):
        return json.JSONDecoder().raw_decode(raw[raw.index('{'):])[0]
    evidence={'viewed_up_to':end,'note':'以下是你自己的历史理解，可能含误判，并不是核实过的剧情事实。不能把旧猜测当结论，也不要使用下一集内容。',
        'chronological_observations':[{k:e.get(k) for k in ('cursor','story','interest')} for e in state['events'] if e['cursor']%60==0 and e['cursor']<=end],
        'latest_memory':state['plot_memory']}
    if state['input'].get('hearing'):
        from reaction_attention import heard_until
        hearing=json.loads(Path(state['input']['hearing']).read_text(encoding='utf-8'))
        evidence['speaker_hypotheses']={k:v[-3:] for k,v in state.get('speaker_hypotheses',{}).items()}
    if not (a.output/'review-plan.json').exists():
        raw=await call(json.dumps(evidence,ensure_ascii=False)+f'\n搭档希望在本集后增加你自己的观后总结：这一集讲了什么、目前对动画的理解、你的感受。先自己决定需要回看哪些已看过的时间点来核对人物和旁白归属，尤其不要把旁白认成画面里角色说的话。只返回JSON {{"review_times":[数字秒数],"questions":"你要核对什么"}}，最多12个时间点，范围0至{last}。')
        plan=obj(raw)
        if not isinstance(plan.get('review_times'),list) or len(plan['review_times'])>12:raise ValueError('Invalid review plan')
        if any(not isinstance(t,(int,float)) or not 0<=t<=last for t in plan['review_times']):raise ValueError('Review exceeds episode')
        save(a.output/'review-plan.json',plan)
    plan=json.loads((a.output/'review-plan.json').read_text(encoding='utf-8'))
    if (a.output/'grounding.json').exists():
        evidence=json.loads((a.output/'grounding.json').read_text(encoding='utf-8'))
    evidence['your_deferred_thoughts']=state.get('deferred',[])
    evidence['deferred_note']='这些是你观看时决定暂不说的想法，不是核实事实，也不要求逐条讲；由你决定片尾还想不想谈。'
    content=[{'type':'text','text':json.dumps({'viewing_evidence':evidence,'your_review_plan':plan},ensure_ascii=False)}]
    if state['input'].get('hearing'):
        selected=[c for c in heard_until(hearing,end) if any(abs(c['start']-t)<=6 for t in plan['review_times'])]
        content.append({'type':'text','text':json.dumps({'timestamped_hearing':selected,'note':'匿名声纹候选不是角色身份，机器转写和归属推断可能出错。'},ensure_ascii=False)})
    for t in plan['review_times']:
        for index in sorted(set(max(0,min(int(last*4),int(t*4)+delta)) for delta in (-2,0,2))):
            path=a.viewing/'observed-frames'/f'{index+1:06d}.jpg'
            content.extend([{'type':'text','text':f'你选择回看的画面 {index/4:.2f} 秒'},
                {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()}}])
    if not (a.output/'reflection.txt').exists():
        if (a.output/'feedback.txt').exists() and not (a.output/'grounding.json').exists():
            content.append({'type':'text','text':json.dumps({'your_previous_draft':(a.output/'previous-draft.txt').read_text(encoding='utf-8'),'fact_review_feedback':(a.output/'feedback.txt').read_text(encoding='utf-8')},ensure_ascii=False)})
        content.append({'type':'text','text':'这一集已看完。请直接说出你的片尾总结，讲讲这一集发生了什么、你现在怎样理解这部动画，以及你自己的感受和还想知道的事。内容取舍和观点由你决定。不使用未看过的剧情，不把没弄清的字幕说话人或旧猜测当事实。这里只能从画面及字幕核对，没有原声输入；有些话是谁的内心独白，不确定就保留不确定。只输出会说出来的文字，表情动作另行选择。'})
        if state['input'].get('hearing'):
            content[-1]['text']=content[-1]['text'].replace('这里只能从画面及字幕核对，没有原声输入；','这里有机器听觉证据及画面，联合核对；')
        text=await call(content)
        (a.output/'reflection.txt').write_text(text,encoding='utf-8')
    text=(a.output/'reflection.txt').read_text(encoding='utf-8')
    audio=a.output/'voice-0.mp3';meta=a.output/'voice-0.jsonl';ff=imageio_ffmpeg.get_ffmpeg_exe()
    if not audio.exists():
        await edge_tts.Communicate(text,'zh-CN-XiaoyiNeural',rate='+10%',pitch='+14Hz',boundary='WordBoundary').save(str(audio),str(meta))
    duration=len(pcm_audio(ff,audio))/8000
    if not (a.output/'performance-plan.json').exists():
        feedback=''
        for attempt in range(4):
            raw=await call(json.dumps({'your_spoken_reflection':text,'speech_duration_seconds':duration},ensure_ascii=False)+'\n为这段自己的片尾发言选择表情动作。可保持自然，也可选择合适的时点；不必整段一直动。只返回JSON {"performances":[{"at":相对语音起点秒数,"performance":{...}}]}。'+feedback,PERFORMANCE_PROMPT)
            try:
                plans=obj(raw)['performances']
                for p in plans:
                    if not isinstance(p['at'],(float,int)) or not 0<=p['at']<=duration:raise ValueError('Invalid performance time')
                    p['performance']=performance(p)
                break
            except (ValueError,KeyError,TypeError) as exc:
                save(a.output/f'unsupported-plan-{attempt}.json',{'raw':raw,'error':str(exc)})
                if attempt==3:raise
                feedback='\n上一版包含不可执行的选项，请自己从所提供的枚举中重新选，不要创造新的表情动作名称。上一版：'+raw
        save(a.output/'performance-plan.json',plans)
    plans=json.loads((a.output/'performance-plan.json').read_text(encoding='utf-8'))
    words=[json.loads(x) for x in meta.read_text(encoding='utf-8').splitlines()]
    event={'id':0,'text':text,'audio':'/audio/voice-0.mp3','captions':caption_pages(text,words),'duration':duration}
    save(a.output/'decisions.json',{'prefixEnabled':bool(prefix.get('enabled')),'events':[event]})
    save(a.output/'clock-metrics.json',{'speed':1,'playbacks':[{'id':0,'wall':1}],
        'performances':[{'wall':p['at']+1,'selected':p['performance']} for p in sorted(plans,key=lambda p:p['at'])]})
    subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=c=0x10263b:s=1920x1080:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-c:a','aac',str(a.output/'silent-source.mp4')],check=True)
    print(json.dumps({'duration':duration,'characters':len(text),'performances':len(plans),'prefixEnabled':bool(prefix.get('enabled'))},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['viewing','output','home','persona']:p.add_argument('--'+name,type=Path,required=True)
    asyncio.run(main(p.parse_args()))
