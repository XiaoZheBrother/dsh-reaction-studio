const $=s=>document.querySelector(s),film=$('#film'),voice=$('#voice');
let config,enabled=false,busy=false,epoch=0,frames=[],cues=[],previous=null,lastCapture=-1,lastSent=-1,started=0,objectUrl,ctx,analyser,bins,zoomPending=false;
let pendingSpeech=null,speechBusy=false,spoken=[],failures=0,speechRevision=0,preparing=null,lastTtsSeconds=null;
let lastDecision=0,ready=false,manualSeek=false,timeline=crypto.randomUUID(),zoomCount=0;
const canvas=document.createElement('canvas'),probe=document.createElement('canvas');probe.width=32;probe.height=18;
const log=(text)=>{const e=document.createElement('div');e.className='entry';e.textContent=text;$('#log').prepend(e);while($('#log').children.length>60)$('#log').lastChild.remove()};
function state(t){$('#status').textContent=t}
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Reaction-Token':config.token},body:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(value.error||'请求失败');return value}
function invalidate(reset=true){epoch++;speechRevision++;pendingSpeech=null;preparing=null;if(reset){spoken=[];timeline=crypto.randomUUID()}frames=[];previous=null;lastCapture=-1;lastSent=-1;voice.pause();$('#zoom').style.display='none';zoomPending=false;zoomCount=0}
function clock(v){return v.split(':').reduce((a,n)=>a*60+Number(n.replace(',','.')),0)}
export function parseSubs(text){return text.replace(/\r/g,'').split(/\n\s*\n/).flatMap(block=>{const lines=block.split('\n'),n=lines.findIndex(l=>l.includes('-->'));if(n<0)return[];const t=lines[n].match(/([\d:.,]+)\s*-->\s*([\d:.,]+)/);if(!t)return[];return[{start:clock(t[1]),end:clock(t[2]),text:lines.slice(n+1).join('\n').replace(/<[^>]*>/g,'')}]})}
$('#subs').onchange=async e=>{const f=e.target.files[0];if(f){if(f.size>2000000)return state('字幕文件过大');cues=parseSubs(await f.text());log(`已载入 ${cues.length} 条字幕；只发送已结束的字幕`)} };
$('#file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(busy){e.target.value='';return state('请等当前请求结束再换视频')}enabled=false;invalidate();cues=[];$('#subs').value='';if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(f);film.src=objectUrl;$('#filename').textContent=f.name;await post('/api/reset',{});$('#start').disabled=false;$('#once').disabled=false;state('视频已载入，等待开始')};
function capture(region='full'){
 if(film.readyState<2||!film.videoWidth)return null;
 let x=0,y=0,w=film.videoWidth,h=film.videoHeight;
 if(region==='left')w/=2;if(region==='right'){w/=2;x=w}if(region==='center'){x=w*.25;y=h*.25;w/=2;h/=2}
 canvas.width=768;canvas.height=Math.round(768*h/w);canvas.getContext('2d').drawImage(film,x,y,w,h,0,0,canvas.width,canvas.height);
 return {at:film.currentTime,image:canvas.toDataURL('image/jpeg',.72)};
}
function sample(){
 if(enabled&&performance.now()-started>300000){enabled=false;invalidate(false);state('本次5分钟观察结束');return}
 if(!enabled||film.paused||film.readyState<2||film.currentTime===lastCapture)return;
 const p=probe.getContext('2d',{willReadFrequently:true});p.drawImage(film,0,0,32,18);const pixels=p.getImageData(0,0,32,18).data;let change=0;
 if(previous)for(let i=0;i<pixels.length;i+=4)change+=Math.abs(pixels[i]-previous[i])+Math.abs(pixels[i+1]-previous[i+1])+Math.abs(pixels[i+2]-previous[i+2]);change/=32*18*3;previous=new Uint8ClampedArray(pixels);
 // Keep sparse baseline plus changes; never decode future frames.
 if(change>12||film.currentTime-lastCapture>=2||lastCapture<0){const f=capture();if(f){frames.push(f);frames=frames.slice(-120);lastCapture=film.currentTime}}
 const interval=8;
 if(film.currentTime-lastSent>=interval&&performance.now()-lastDecision>4000)observe();
}
async function speak(text,generation,cursor,ttl=12,revision=speechRevision){
 const ttsStart=performance.now();const r=await post('/api/speak',{text});lastTtsSeconds=(performance.now()-ttsStart)/1000;if(generation!==epoch||revision!==speechRevision)return;
 if(!film.paused&&Math.abs(film.currentTime-cursor)>ttl){log('语音合成后已错过当前镜头，跳过播放');return}
 if(!r.audio){log(r.warning||'语音暂不可用');return}
 if(!ctx){ctx=new AudioContext();const source=ctx.createMediaElementSource(voice);analyser=ctx.createAnalyser();analyser.fftSize=256;bins=new Uint8Array(analyser.fftSize);source.connect(analyser);analyser.connect(ctx.destination)}
 await ctx.resume();if(generation!==epoch||revision!==speechRevision)return;voice.src=r.audio;await voice.play();if(generation!==epoch||revision!==speechRevision){voice.pause();return}$('#reply').textContent=text;spoken.push({at:cursor,text});spoken=spoken.slice(-4);
}
function cancelPending(){speechRevision++;pendingSpeech=null;preparing=null}
function queueSpeech(text,generation,cursor,ttl=12){speechRevision++;pendingSpeech={text,generation,cursor,ttl,revision:speechRevision};pumpSpeech()}
async function pumpSpeech(){
 if(speechBusy||!voice.paused||!pendingSpeech)return;
 const job=pendingSpeech;pendingSpeech=null;
 if(job.generation!==epoch||Math.abs(film.currentTime-job.cursor)>job.ttl){log('已丢弃过时的待说内容');return}
 speechBusy=true;preparing=job;
 try{await speak(job.text,job.generation,job.cursor,job.ttl,job.revision)}catch(e){log('语音失败：'+e.message)}finally{speechBusy=false;preparing=null}
}
async function observe(question='',forced=false){
 if(!config||busy||(!enabled&&!forced))return;
 const f=capture();if(!f)return;const all=frames.concat(f);const batch=all.length<=8?all:Array.from({length:8},(_,i)=>all[Math.round(i*(all.length-1)/7)]);frames=[];
 const cursor=film.currentTime,generation=epoch;lastSent=cursor;lastDecision=performance.now();busy=true;state('正在看这一段');$('#error').textContent='';
 const frozen=document.createElement('canvas');frozen.width=film.videoWidth;frozen.height=film.videoHeight;frozen.getContext('2d').drawImage(film,0,0);
 $('#frames').replaceChildren(...batch.map(f=>{const i=new Image();i.src=f.image;i.title=f.at.toFixed(2)+'秒';return i}));
 try{
 const r=await post('/api/observe',{timeline,cursor,frames:batch,cues:cues.filter(c=>c.end<=cursor&&c.end>=Math.max(0,cursor-20)).slice(-30),question,playback:{recentSpeechSeconds:lastTtsSeconds,busy:speechBusy||!voice.paused,pending:pendingSpeech?{text:pendingSpeech.text,at:pendingSpeech.cursor}:preparing?{text:preparing.text,at:preparing.cursor}:null,spoken}});
 if(generation!==epoch)return;
 failures=0;$('#stats').textContent=` · ${r.calls} 次 · ${r.tokens} Token · 本轮 ${r.elapsed}s · 前缀${r.prefixEnabled?'开':'关'}`;
 if(r.budget)$('#budget').textContent=`输入预算估算 ${r.budget.estimatedInput}/${r.budget.inputLimit} · 实际 ${r.budget.actualInput??'—'} Token · 近期 ${r.budget.recentKept} 条 · 较早 ${r.budget.olderOmitted} 条由概要承接`;
 log(`${cursor.toFixed(1)}s · ${r.action} · ${r.reason}`);$('#story').textContent=r.story||'尚无剧情记录';$('#uncertain').textContent=r.uncertain||'暂无';$('#interest').textContent=r.interest||'暂无';
 const controlFresh=Math.abs(film.currentTime-cursor)<=12;
 if(!controlFresh&&['pause','zoom','replay'].includes(r.action))log('画面已变化，跳过迟到的播放器动作');
 if(controlFresh&&(r.action==='pause'||r.action==='zoom'))film.pause();
 if(controlFresh&&r.action==='replay'){const target=Math.max(0,cursor-r.seconds);if(Math.abs(film.currentTime-target)>.05){manualSeek=true;film.currentTime=target}frames=[];lastCapture=-1;lastSent=target;await film.play()}
 if(controlFresh&&r.action==='zoom'){let x=0,y=0,w=frozen.width,h=frozen.height;if(r.region==='left')w/=2;if(r.region==='right'){w/=2;x=w}if(r.region==='center'){x=w*.25;y=h*.25;w/=2;h/=2}canvas.width=768;canvas.height=Math.round(768*h/w);canvas.getContext('2d').drawImage(frozen,x,y,w,h,0,0,canvas.width,canvas.height);const z={at:cursor,image:canvas.toDataURL('image/jpeg',.8)};$('#zoom').src=z.image;$('#zoom').style.display='block';frames=[z];zoomPending=++zoomCount<=2}
 if(r.pending==='cancel')cancelPending();
 if(r.text)queueSpeech(r.text,generation,controlFresh&&r.action==='replay'?film.currentTime:cursor,r.ttl??12);
 state(r.action==='silent'?'她选择继续安静看':film.paused?'已暂停，等你继续':'正在陪看');
 }catch(e){if(generation!==epoch)return;failures++;$('#error').textContent=e.message;log('本轮观察失败，保留先前剧情');if(failures>=3){enabled=false;invalidate(false);state('连续3次失败，已停止观察')}else state('本轮跳过，下轮继续观察')}finally{busy=false}
}
$('#start').onclick=async()=>{await (ctx?.resume());enabled=true;failures=0;started=performance.now();lastSent=film.currentTime-8;await film.play();state('正在陪看')};
$('#stop').onclick=()=>{enabled=false;invalidate(false);state('已停止观察，视频可继续播放')};
$('#once').onclick=()=>observe('',true);$('#ask').onclick=()=>{const q=$('#question').value;$('#question').value='';observe(q,true)};
$('#resume').onclick=()=>{$('#zoom').style.display='none';zoomPending=false;zoomCount=0;film.play()};
film.addEventListener('seeking',()=>{if(manualSeek){manualSeek=false;return}invalidate();log('手动跳转，已取消旧位置的回应')});
film.addEventListener('ended',()=>{enabled=false;state('影片已结束')});
film.addEventListener('error',()=>state('无法播放此格式，请换浏览器支持的 MP4/WebM'));
setInterval(()=>{sample();pumpSpeech();$('#film-sub').textContent=cues.filter(c=>c.start<=film.currentTime&&c.end>film.currentTime).map(c=>c.text).join('\n');if(zoomPending&&!busy&&voice.paused){zoomPending=false;observe('这是你请求放大的刚才画面。',true)}},500);
config=await(await fetch('/api/config')).json();$('#pet').src=config.jingyuUrl;const target=new URL(config.jingyuUrl).origin;
window.addEventListener('message',e=>{if(e.origin===target&&e.source===$('#pet').contentWindow&&e.data?.type==='lane-ready'){ready=true;log('Live2D 已连接')}});
function sync(){let rms=0;if(analyser&&!voice.paused){analyser.getByteTimeDomainData(bins);for(const b of bins)rms+=((b-128)/128)**2;rms=Math.sqrt(rms/bins.length)}if(ready)$('#pet').contentWindow.postMessage({type:'sync',text:$('#reply').textContent,audio:{paused:voice.paused,currentTime:voice.currentTime,duration:Number.isFinite(voice.duration)?voice.duration:0},level:Math.min(1,rms*5)},target);requestAnimationFrame(sync)}sync();state('等待选择视频');
