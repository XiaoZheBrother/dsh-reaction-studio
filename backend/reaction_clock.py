"""Record a slowed watch-along with one actual playback clock, then restore speed."""
import argparse,asyncio,json,secrets,time,subprocess,re
from pathlib import Path
from aiohttp import web,ClientSession
from playwright.async_api import async_playwright
from reaction_server import Reactor,validate_input
from reaction_intent import INTENT_PROMPT,parse_intent
from reaction_render import caption_groups,caption_pages
from reaction_performance import EXPRESSIONS,GESTURES,PERFORMANCE_PROMPT,validate_performance
from live_pilot_chat import generator
import edge_tts,imageio_ffmpeg

def can_voice(intent, playback):
    """Defer thoughts while the voice is occupied; do not queue stale sentences."""
    return intent.get('action') == 'speak' and not playback.get('busy') and not playback.get('pending')

async def main(args):
    args.output.mkdir(parents=True,exist_ok=getattr(args,"follow",False))
    engine=Reactor(args.home,args.persona)
    system,prefix,key=([{'content':''}],{},None) if args.replay else generator.load_context(args.home,args.persona,scene='reaction_offline')
    gate_system=system[0]['content']+'\n'+INTENT_PROMPT[INTENT_PROMPT.index('这一步只作内部选择'):]+'\n当前是在陪搭档一起看影片，影片以四分之一速度连续播放。这次收到已播放的新画面，请按自己的想法决定：有想说的话就选speak；想接着看就选continue；想重看就选replay。三种选择都正常。表达不要求先解开剧情疑问，不需要证明有必要发言；也不需要为了回应这次调用而说话。playback是正在说的话和还没说出的想法。正在说话时，新的想法先保留；说完后由你结合最新画面决定是否还想说，也可改变或放下先前想法。'
    gate_system+='\n'+PERFORMANCE_PROMPT
    token=secrets.token_urlsafe(32);history=[];results=[];played=[];lock=asyncio.Lock();root=Path(__file__).parent;ff=imageio_ffmpeg.get_ffmpeg_exe()
    if args.context:
        previous=json.loads(args.context.read_text(encoding='utf-8'))['events']
        history.extend({'at':e['cursor'],'story':e.get('story',''),'interest':e.get('interest',''),'choice':e['action']} for e in previous if e['cursor']<=args.start)
    @web.middleware
    async def local_only(request, handler):
        if request.host != f'127.0.0.1:{args.port}':raise web.HTTPForbidden()
        return await handler(request)
    app=web.Application(client_max_size=512*1024*1024,middlewares=[local_only])
    def authorized(request):
        if request.headers.get('X-Clock-Token')!=token or request.headers.get('Origin')!=f'http://127.0.0.1:{args.port}':raise web.HTTPForbidden()
    async def index(request):return web.FileResponse(root/'reaction_clock.html')
    replay=None;replay_performances=[]
    if args.replay:
        old=json.loads((args.timeline or args.replay/'clock-metrics.json').read_text(encoding='utf-8'))
        choices={e['id']:e for e in json.loads((args.replay/'decisions.json').read_text(encoding='utf-8'))['events']}
        replay_performances=[{**e,'at':e['wall']*old['speed']/args.speed} for e in old.get('performances',[])]
        replay=[{**choices[e['id']],'at':e['wall']*old['speed']/args.speed} for e in old['playbacks']]
        for e in replay:
            words=[json.loads(line) for line in (args.replay/(Path(e['audio']).stem+'.jsonl')).read_text(encoding='utf-8').splitlines()]
            e['captions']=caption_pages(e['text'],words)
    async def config(request):return web.json_response({'token':token,'speed':args.speed,'seconds':args.seconds,'start':args.start,'observeStep':2,'replay':replay,'replayPerformances':replay_performances,'offline':args.offline,'epilogue':getattr(args,'epilogue',False),'fps':24,'episodeLabel':args.episode_label,'characterName':args.character_name})
    async def source_frame(request):
        name=request.match_info['name']
        if not re.fullmatch(r'\d{6}\.jpg',name):raise web.HTTPNotFound()
        return web.FileResponse(args.output/'source-frames'/name)
    async def background(request):return web.FileResponse(root/'assets'/'reaction-undersea-room.png')
    async def source(request):return web.FileResponse(args.video)
    async def assets(request):
        path=request.path
        if not (path.startswith('/vendor/') or path.startswith('/model/')):raise web.HTTPNotFound()
        async with ClientSession() as session:
            async with session.get(args.jingyu_url.rstrip('/')+path) as response:
                return web.Response(body=await response.read(),status=response.status,headers={'Content-Type':response.headers.get('Content-Type','application/octet-stream')})
    async def avatar_catalog(request):
        async with ClientSession() as session:
            async def get(path):
                async with session.get(args.jingyu_url.rstrip('/')+'/model/'+path) as response:
                    response.raise_for_status();return await response.json(content_type=None)
            config=await get(args.model_file)
            expressions={name:await get('Exp3/'+name+'.exp3.json') for name in EXPRESSIONS if name not in ('keep','neutral','微笑')}
            expressions['微笑']={'Parameters':[{'Id':'EyeSmile','Value':.7,'Blend':'Overwrite'},{'Id':'ParamMouthForm','Value':.6,'Blend':'Overwrite'}]}
            config['FileReferences']['Motions']={key+'_'+suffix:[{'File':'Animation/'+file+'.motion3.json'}] for key,pair in GESTURES.items() for suffix,file in zip(['enter','exit'],pair)}
            return web.json_response({'settings':config,'expressions':expressions,'modelFile':args.model_file})
    async def audio(request):
        name=request.match_info['name']
        if not re.fullmatch(r'voice-\d+(?:-r\d+)?\.mp3',name):raise web.HTTPNotFound()
        return web.FileResponse((args.replay or args.output)/name)
    async def saved(request):
        authorized(request)
        name={'/recording':'capture-slow.webm','/metrics':'clock-metrics.json'}[request.path]
        (args.output/name).write_bytes(await request.read());return web.json_response({'ok':True})
    async def playback(request):
        authorized(request);played.append(await request.json());return web.json_response({'ok':True})
    async def observe(request):
        authorized(request)
        if lock.locked():return web.json_response({'error':'observation in flight'},status=409)
        async with lock:
            body=validate_input(await request.json());cursor=body['cursor'];start=time.monotonic()
            content=[{'type':'text','text':json.dumps({'cursor':cursor,'viewed_up_to':cursor,'duration':1420,'previous_observations':[{k:v for k,v in h.items() if k!='choice'} for h in history[-12:]],'actually_spoken':played[-5:],'playback':body.get('playback',{})},ensure_ascii=False)}]
            for f in body['frames']:content.extend([{'type':'text','text':f"已看画面 {f['at']:.2f} 秒"},{'type':'image_url','image_url':{'url':f['image']}}])
            messages=[{'role':'system','content':gate_system},{'role':'user','content':content}]
            if prefix.get('enabled'):messages.append({'role':'assistant','content':'','prefix':True,'reasoning_content':prefix['prefix']})
            event={'id':len(results),'cursor':cursor,'frames':[f['at'] for f in body['frames']]}
            try:
                raw,_=await engine.complete(messages,key)
                event['raw_intent']=raw;intent=parse_intent(raw,0,cursor);event.update(intent)
                try:event['performance']=validate_performance(intent.get('performance'))
                except ValueError as exc:event['performance']=validate_performance(None);event['performance_error']=str(exc)
                history.append({'at':cursor,'story':intent.get('story',''),'interest':intent.get('interest',''),'choice':intent['action']})
                if can_voice(intent, body.get('playback',{})):
                    expression=[{'role':'system','content':system[0]['content']+'\n你已自主决定开口，请根据自己的意图和画面直接说出想说的话，不念分析字段。本次是短样片，一次口播最多140字。没有原声音频输入，不臆测音色。'}, {'role':'user','content':content+[{'type':'text','text':json.dumps({'your_intent':intent},ensure_ascii=False)}]}]
                    if prefix.get('enabled'):expression.append(messages[-1])
                    text,_=await engine.complete(expression,key)
                    if not text or len(text)>220:raise ValueError('spoken output exceeds preview capacity')
                    event['text']=text;name=f"voice-{event['id']}";audio_path=args.output/f'{name}.mp3';meta=args.output/f'{name}.jsonl'
                    for attempt in range(2):
                        try:
                            await asyncio.wait_for(edge_tts.Communicate(text,'zh-CN-XiaoyiNeural',rate='+10%',pitch='+14Hz',boundary='WordBoundary',receive_timeout=12).save(str(audio_path),str(meta)),20)
                            break
                        except Exception:
                            if attempt:raise
                    words=[json.loads(line) for line in meta.read_text(encoding='utf-8').splitlines()]
                    event.update(audio='/audio/'+audio_path.name,captions=caption_pages(text,words))
                event['seconds']=intent.get('seconds',5)
            except Exception as exc:event['error']=type(exc).__name__+': '+str(exc)[:160];event['action']='error';event.pop('audio',None)
            event['processing_seconds']=time.monotonic()-start;results.append(event)
            (args.output/'decisions.json').write_text(json.dumps({'speed':args.speed,'prefixEnabled':bool(prefix.get('enabled')),'events':results},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'cursor':round(cursor,2),'action':event.get('action'),'processing_seconds':round(event['processing_seconds'],2),'error':event.get('error')},ensure_ascii=False),flush=True)
            return web.json_response(event)
    app.router.add_get('/live-performance.mjs',lambda request:web.FileResponse(Path(__import__('live_performance').__file__).with_name('live-performance.mjs')));app.router.add_get('/source-frame/{name}',source_frame);app.router.add_get('/avatar-catalog',avatar_catalog);app.router.add_get('/background',background);app.router.add_get('/',index);app.router.add_get('/config',config);app.router.add_get('/source',source);app.router.add_get('/audio/{name}',audio)
    app.router.add_post('/observe',observe);app.router.add_post('/played',playback);app.router.add_post('/recording',saved);app.router.add_post('/metrics',saved)
    app.router.add_get('/{tail:.*}',assets)
    runner=web.AppRunner(app);await runner.setup();await web.TCPSite(runner,'127.0.0.1',args.port).start()
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True,executable_path=args.chromium,args=['--autoplay-policy=no-user-gesture-required','--enable-unsafe-swiftshader']+(['--use-angle=d3d11','--enable-gpu'] if getattr(args,'hardware_renderer',False) else []))
            page=await browser.new_page(viewport={'width':1920,'height':1080})
            page.on('pageerror',lambda error:print('PAGE ERROR '+error.stack,flush=True))
            await page.goto(f'http://127.0.0.1:{args.port}/')
            await page.wait_for_function('window.ready===true',timeout=90000)
            await page.screenshot(path=str(args.output/'model-ready.png'))
            if args.offline:
                from reaction_frame_render import render_frames
                await render_frames(page,args,replay,replay_performances,ff)
                await browser.close()
                return
            await page.evaluate('window.start()')
            for i in range(180):
                await asyncio.sleep(3)
                state=await page.evaluate('({done:window.done,failure:window.failure,source:document.querySelector("#film").currentTime})')
                if i%10==0:
                    snapshot=await page.evaluate('window.clockSnapshot()');(args.output/'clock-live.json').write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
                if i%10==0:print(json.dumps({'watching':state}),flush=True)
                if state.get('failure'):raise RuntimeError(state['failure'])
                if state.get('done'):break
            else:
                await page.evaluate('window.finish()')
                raise TimeoutError('Clock pilot exceeded recording limit; partial recording saved')
            await page.screenshot(path=str(args.output/'capture-end.png'));await browser.close()
    finally:await runner.cleanup()
    # Browser resampling lowered pitch with speed; restore rate once for both tracks.
    subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-i',str(args.output/'capture-slow.webm'),'-vf',f'setpts={args.speed}*(PTS-STARTPTS)','-af',f'asetrate={48000/args.speed},aresample=48000','-r','30','-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-b:a','192k','-movflags','+faststart',str(args.output/'大肥鱼陪看样片.mp4')],check=True)
    print('RENDER COMPLETE',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--home',type=Path,required=True);p.add_argument('--persona',type=Path,required=True);p.add_argument('--seconds',type=float,default=60);p.add_argument('--start',type=float,default=0);p.add_argument('--context',type=Path);p.add_argument('--speed',type=float,default=.25);p.add_argument('--port',type=int,default=3111);p.add_argument('--chromium');p.add_argument('--replay',type=Path);p.add_argument('--timeline',type=Path);p.add_argument('--offline',action='store_true');p.add_argument('--hardware-renderer',action='store_true');p.add_argument('--follow',action='store_true');p.add_argument('--epilogue',action='store_true');p.add_argument('--jingyu-url',default='http://127.0.0.1:61949');p.add_argument('--model-file',default='大肥鱼.model3.json');p.add_argument('--episode-label',default='这一集');p.add_argument('--character-name',default='大肥鱼');a=p.parse_args()
    if not .1<=a.speed<=1 or not 1<=a.seconds<=(14400 if a.offline else 90):p.error('invalid clock limits')
    if a.offline and (not a.replay or a.speed!=1):p.error('offline render requires --replay and --speed 1')
    from urllib.parse import urlsplit
    u=urlsplit(a.jingyu_url)
    if u.scheme!='http' or u.hostname not in ('localhost','127.0.0.1') or u.username or u.password or u.query or u.fragment:p.error('jingyu-url must be loopback HTTP')
    if Path(a.model_file).name!=a.model_file or not a.model_file.endswith('.model3.json'):p.error('invalid model file')
    asyncio.run(main(a))
