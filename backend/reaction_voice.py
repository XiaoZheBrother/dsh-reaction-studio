"""Confirmed voice presets, cached preparation and B-audition loudness treatment."""
import hashlib,json,math,os,subprocess,sys
from pathlib import Path
from reaction_episode import save

def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def load_voice(settings):
    profile=settings['profile']
    if isinstance(profile,str):profile=json.loads(Path(profile).read_text('utf-8'))
    if profile.get('engine')!='IndexTTS2' or not profile.get('presets'):raise ValueError('Missing confirmed voice profile')
    ids=set()
    for preset in profile['presets']:
        vector=preset.get('emotion_vector');pid=str(preset.get('id',''))
        if not pid or pid in ids or not isinstance(vector,list) or len(vector)!=8 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in vector):raise ValueError('Invalid confirmed voice preset')
        ids.add(pid)
    return profile

async def prepare_voice(text,settings,root,ask,context):
    """ask(prompt,context,parser) uses the caller's existing persona/memory/prefix."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True);profile=load_voice(settings)
    config=settings.get('config_snapshot') or json.loads(Path(settings['config']).read_text('utf-8-sig'))
    reference=Path(config['assets'][settings.get('reference','voice-reference')]['path'])
    reference_hash=hashlib.sha256(reference.read_bytes()).hexdigest()
    if settings.get('reference_sha256') and settings['reference_sha256']!=reference_hash:raise ValueError('Confirmed voice reference changed; start a new job after confirming it')
    key=identity({'text':text,'profile':profile,'context':context,'config':config,'reference_sha256':reference_hash});folder=root/key;folder.mkdir(exist_ok=True)
    if (folder/'result.json').exists():
        result=json.loads((folder/'result.json').read_text('utf-8'))
        path=Path(result['path'])
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==result['sha256']:return result
    choices={str(p['id']):p for p in profile['presets']}
    def parse(raw):
        value,_=json.JSONDecoder().raw_decode(raw[raw.index('{'):])
        if str(value.get('preset_id')) not in choices or not isinstance(value.get('intent'),str):raise ValueError('Choose a confirmed preset')
        return value
    selected_path=folder/'delivery.json'
    if selected_path.exists():selected=json.loads(selected_path.read_text('utf-8'))
    else:
        selected=await ask('给自己这段话选择说法。声音固定用搭档确认的B；从以下已确认的参数中自己选择，不自由重配八维值。这里是声音能力边界，不是人设要求，不需要模仿示例内容。只返回JSON {"preset_id":"参数ID","intent":"你想怎么说"}。',dict(context,text=text,confirmed_presets=list(choices.values())),parse)
        save(selected_path,selected)
    preset=choices[str(selected['preset_id'])]
    config=dict(config)
    config['workspace']=str(root/'store');config_path=folder/'audio-config.json';save(config_path,config)
    project='voice-'+key[:24];work=Path(config['workspace'])/project
    request={'text':text,'reference_asset':settings.get('reference','voice-reference'),'emotion_vector':preset['emotion_vector']}
    (work/'jobs').mkdir(parents=True,exist_ok=True);save(work/'jobs'/'prepare.json',request)
    subprocess.run([settings['python'],str(Path(settings['backend'])/'audio_worker.py'),'--config',str(config_path),'--project',project,'--job','prepare'],check=True,
        env={**os.environ,'PYTHONUTF8':'1'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    prepared=json.loads((work/'prepared.json').read_text('utf-8'))
    source=Path(config['workspace'])/'generated'/(prepared['audio']+'.wav')
    import imageio_ffmpeg
    ff=imageio_ffmpeg.get_ffmpeg_exe();target=folder/'voice.wav'
    # Same two-pass normalization as the approved B audition. Never time-stretch.
    measure=subprocess.run([ff,'-hide_banner','-i',str(source),'-af','loudnorm=I=-18:TP=-2:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
    stats=json.loads(measure.stderr[measure.stderr.rfind('{'):measure.stderr.rfind('}')+1])
    filt=f"loudnorm=I=-18:TP=-2:LRA=11:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true"
    subprocess.run([ff,'-v','error','-y','-i',str(source),'-af',filt,'-ar','48000','-ac','1',str(target)],check=True)
    result={**prepared,'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'delivery':selected,'voice_profile':profile['id'],'preset':preset['id'],'loudness':stats,'normalization':{'integrated_lufs':-18,'true_peak_db':-2,'time_stretch':False}}
    save(folder/'result.json',result);return result
