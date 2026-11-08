"""One resumable offline production command. Never publishes or starts Bili tasks.

python backend/reaction_produce.py --job /absolute/path/job.json
Job keys: video, output, home, persona, seconds, chromium; optional step, port.
The viewer owns editorial decisions; export always uses source-speed video and
normal-speed speech, with explicit pauses on their shared composition timeline.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys

# Restore the installed shared component for independently scheduled workers and
# all renderer subprocesses, before importing any media modules.
if __name__ == '__main__':
    bootstrap=argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument('--job',required=True)
    early,_=bootstrap.parse_known_args()
    shared=json.loads(Path(early.job).read_text(encoding='utf-8-sig')).get('live_backend')
    if shared:
        shared_path=Path(shared).resolve()
        if not (shared_path/'live_performance.py').is_file():
            raise ValueError('Configured live plugin backend is missing; reinstall matching release')
        sys.path.insert(0,str(shared_path))
        os.environ['PYTHONPATH']=os.pathsep.join(filter(None,[str(shared_path),os.environ.get('PYTHONPATH')]))

import imageio_ffmpeg
from reaction_episode import save


from reaction_job_control import exclusive_job


def produce(job):
    for name in ('video','output','home','persona','chromium'):
        if not Path(job[name]).is_absolute():raise ValueError(f'{name} must be absolute')
    seconds=job['seconds']
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 0<seconds<=14400:
        raise ValueError('Invalid source trim')
    root=Path(job['output']);root.mkdir(parents=True,exist_ok=True)
    backend=Path(__file__).resolve().parent
    state_path=root/'production.json'
    with exclusive_job(root/'.production.lock'):
        print(json.dumps({'renderer_exists':Path(job['chromium']).is_file(),'renderer_executable':os.access(job['chromium'],os.X_OK),'working_directory':str(Path.cwd())}),flush=True)
        manifest=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'job':job,'phase':'new'}
        if manifest['job']!=job:raise ValueError('Use a new job directory for changed settings')
        def phase(name,**extra):
            if name!='failed':
                manifest.pop('error',None);manifest.pop('failed_at',None)
            manifest.update(phase=name,**extra);save(state_path,manifest)
        def run(script,args):
            subprocess.run([sys.executable,'-u',str(backend/script),*map(str,args)],check=True,
                stdout=sys.stdout,stderr=sys.stderr,
                env={**os.environ,'PYTHONUTF8':'1'},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        avatar=['--episode-label',job.get('episode_label','这一集'),'--character-name',job.get('character_name','大肥鱼'),'--jingyu-url',job.get('jingyu_url','http://127.0.0.1:61949'),'--model-file',job.get('model_file','大肥鱼.model3.json')]
        if job.get('model_dir') and job.get('cubism_core'):avatar += ['--model-dir',job['model_dir'],'--cubism-core',job['cubism_core']]
        common=['--video',job['video'],'--home',job['home'],'--persona',job['persona'],'--seconds',seconds]
        try:
            if job.get('hearing_python'):
                hearing_path=root/'hearing.json'
                if not hearing_path.exists() or not json.loads(hearing_path.read_text(encoding='utf-8')).get('complete'):
                    phase('hearing')
                    subprocess.run([job['hearing_python'],'-u',str(backend/'reaction_hearing.py'),'--video',job['video'],
                        '--seconds',str(seconds),'--output',str(hearing_path),'--models',job['hearing_models']],check=True,
                        stdout=sys.stdout,stderr=sys.stderr,env={**os.environ,'PYTHONUTF8':'1','HF_HUB_DISABLE_XET':'1'},
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            phase('viewing')
            hearing_file=str(root/'hearing.json') if job.get('hearing_python') else job.get('hearing')
            hearing_args=['--hearing',hearing_file] if hearing_file else []
            run('reaction_episode.py',common+['--output',root/'viewing','--step',job.get('step',2)]+hearing_args)
            phase('rendering')
            # A completed render is reusable; partial renders resume from frames.
            report_path=root/'render'/'render-report.json'
            if not report_path.exists():
                run('reaction_clock.py',common+avatar+['--output',root/'render','--replay',root/'viewing',
                    '--offline','--follow','--speed',1,'--hardware-renderer','--chromium',job['chromium'],
                    '--port',job.get('port',3111)])
            video=root/'render'/'大肥鱼陪看-第一季01完整版.mp4'
            ff=imageio_ffmpeg.get_ffmpeg_exe()
            report=json.loads(report_path.read_text(encoding='utf-8'))
            if job.get('afterword',False):
                phase('afterword')
                run('reaction_afterword.py',['--viewing',root/'viewing','--output',root/'afterword',
                    '--home',job['home'],'--persona',job['persona']])
                ending=Path(manifest.get('afterword_render',root/'afterword'/'render'))
                if not (ending/'render-report.json').exists():
                    # Resume uses the streaming renderer only for the main film;
                    # the small ending is restarted in a fresh render directory.
                    if ending.exists():
                        number=1
                        while (root/'afterword'/f'render-{number}').exists():number+=1
                        ending=root/'afterword'/f'render-{number}'
                    phase('afterword',afterword_render=str(ending))
                    run('reaction_clock.py',avatar+['--video',root/'afterword'/'silent-source.mp4',
                        '--output',ending,'--home',job['home'],'--persona',job['persona'],
                        '--seconds',1,'--speed',1,'--replay',root/'afterword','--offline','--epilogue',
                        '--hardware-renderer','--chromium',job['chromium'],'--port',job.get('port',3111)])
                tail=json.loads((ending/'render-report.json').read_text(encoding='utf-8'))
                merged=root/'reaction-with-afterword.mp4'
                filters=(f"[0:v]setpts=PTS-STARTPTS[v0];[1:v]setpts=PTS-STARTPTS[v1];"
                         f"[0:a]atrim=duration={report['duration']},asetpts=PTS-STARTPTS[a0];"
                         f"[1:a]atrim=duration={tail['duration']},asetpts=PTS-STARTPTS[a1];"
                         '[v0][a0][v1][a1]concat=n=2:v=1:a=1[vj][aj];'
                         '[vj]settb=1/24,setpts=N[v];[aj]alimiter=limit=0.891251:level=0:latency=1[a]')
                subprocess.run([ff,'-v','error','-y','-i',str(video),'-i',str(ending/'大肥鱼陪看-流畅多行字幕版.mp4'),
                    '-filter_complex',filters,'-map','[v]','-map','[a]','-r','24','-fps_mode','cfr',
                    '-c:v','libx264','-threads','2','-preset','fast','-crf','18','-c:a','aac','-b:a','192k',
                    '-movflags','+faststart',str(merged)],check=True)
                video=merged
                report['duration']+=tail['duration']
            phase('verifying')
            check=subprocess.run([ff,'-v','error','-xerror','-i',str(video),'-f','null','-'],capture_output=True)
            (root/'decode-validation.log').write_bytes(check.stderr)
            check.check_returncode()
            if report['source_end']!=seconds:raise ValueError('Wrong source trim')
            phase('complete',video=str(video),source_seconds=seconds,output_seconds=report['duration'],
                  fps=report['fps'],speech_count=report['speech_count'],pauses=len(report.get('pauses',[])))
            return manifest
        except BaseException as exc:
            phase('failed',failed_at=manifest['phase'],error=type(exc).__name__)
            raise


PRODUCTION_TOOLS=[
    {'name':'reaction_produce','description':'执行当前已配置素材的陪看、配音、正常速度合成和校验；可断点继续，不发布视频。','arguments':{}},
    {'name':'reaction_production_status','description':'读取当前制作状态及最终文件，不启动任务。','arguments':{}},
]


def execute_production_tool(job, call):
    if call.get('arguments',{})!={}:raise ValueError('Production tools only use the host-configured job')
    if call.get('name')=='reaction_produce':return produce(job)
    if call.get('name')=='reaction_production_status':
        path=Path(job['output'])/'production.json'
        if not path.exists():return {'phase':'not_started'}
        data=json.loads(path.read_text(encoding='utf-8'))
        return {k:v for k,v in data.items() if k!='job'}
    raise ValueError('Unknown production tool')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True)
    p.add_argument('--log',type=Path)
    p.add_argument('--tool',choices=['reaction_produce','reaction_production_status'],default='reaction_produce')
    a=p.parse_args()
    if a.log:
        log=a.log.open('a',encoding='utf-8',buffering=1)
        sys.stdout=log;sys.stderr=log
    result=execute_production_tool(json.loads(a.job.read_text(encoding='utf-8-sig')),{'name':a.tool,'arguments':{}})
    print(json.dumps({k:v for k,v in result.items() if k!='job'},ensure_ascii=False),flush=True)
