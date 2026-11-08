"""Register bounded production tools on an existing FastMCP host.

MCP host uses its own Python; the configured worker Python owns media dependencies.
No credentials, persona, formal memory, Bili schedules or arbitrary shell access.
"""
import json
import base64
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from reaction_job_control import exclusive_job, write_json


class ReactionJobs:
    def __init__(self,config_path):
        self.config=json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        self.root=Path(self.config['job_root']).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock()

    def folder(self,job_id):
        if not isinstance(job_id,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',job_id):raise ValueError('Invalid job id')
        path=self.root/job_id
        if path.resolve().parent!=self.root:raise ValueError('Job path escaped root')
        return path

    def active(self,path):
        if not path.exists():return False
        try:
            with exclusive_job(path/'.production.lock'):pass
        except RuntimeError:return True
        launch=path/'launch.json'
        if launch.exists():
            info=json.loads(launch.read_text(encoding='utf-8'))
            manifest=path/'production.json'
            terminal=manifest.exists() and manifest.stat().st_mtime>=info['at'] and json.loads(manifest.read_text(encoding='utf-8')).get('phase') in ('complete','failed')
            return not terminal and time.time()-info['at']<30
        return False

    def catalog(self):
        return {'materials':[{'id':k,'title':v['title'],'max_seconds':v['seconds']} for k,v in self.config['materials'].items()],
                'workflow':'start -> status/observation -> optional pause_analysis/replay -> automatic normal-speed video; no publishing',
                'jobs':[self.status(p.name) for p in self.root.iterdir() if p.is_dir() and (p/'job.json').exists()]}

    def start(self,material_id,job_id,seconds=0,afterword=True):
        if material_id not in self.config['materials']:raise ValueError('Choose a configured material id')
        material=self.config['materials'][material_id]
        seconds=seconds or material['seconds']
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 0<seconds<=material['seconds']:raise ValueError('Outside approved source duration')
        if not isinstance(afterword,bool):raise ValueError('afterword must be boolean')
        path=self.folder(job_id)
        job={k:self.config[k] for k in ('home','persona','chromium')}
        # Scheduled tasks do not inherit the MCP process's Python search path.
        import importlib.util
        shared=importlib.util.find_spec('live_performance')
        if shared:
            job['live_backend']=str(Path(shared.origin).parent)
        job.update(video=material['path'],output=str(path),seconds=seconds,step=2,port=self.config.get('port',3113),afterword=afterword)
        job.update(episode_label=material['title'],character_name=self.config.get('character_name','大肥鱼'))
        job.update(jingyu_url=self.config.get('jingyu_url','http://127.0.0.1:61949'),model_file=self.config.get('model_file','大肥鱼.model3.json'))
        if self.config.get('hearing_python'):
            job.update(hearing_python=self.config['hearing_python'],hearing_models=self.config['hearing_models'])
        with self.lock,exclusive_job(self.root/'.manager.lock'):
            if (path/'job.json').exists():
                existing=json.loads((path/'job.json').read_text(encoding='utf-8'))
                if any(existing.get(k)!=job.get(k) for k in ('home','persona','video','output','seconds','afterword')):
                    raise ValueError('Job id already bound to different settings')
                # Config upgrades affect new jobs only. Resume the recorded pipeline.
                job=existing
                status=self.status(job_id)
                if status['running'] or status['phase']=='complete':return status
            others=[p.name for p in self.root.iterdir() if p.is_dir() and p!=path and self.active(p)]
            if others:raise ValueError('Another reaction job is running: '+','.join(others))
            path.mkdir(exist_ok=True);write_json(path/'job.json',job)
            write_json(path/'launch.json',{'at':time.time(),'material':material_id})
            if self.config.get('launcher')=='windows-task':
                task='Feiyu-Reaction-'+job_id
                def quote(value):return "'"+str(value).replace("'","''")+"'"
                argv=subprocess.list2cmdline(['-u',str(Path(__file__).with_name('reaction_produce.py')),'--job',str(path/'job.json'),'--log',str(path/'worker.log')])
                script=("$ErrorActionPreference='Stop'; "
                    f"$action=New-ScheduledTaskAction -Execute {quote(self.config['python'])} -Argument {quote(argv)}; "
                    "$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited; "
                    "$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 12) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
                    f"Register-ScheduledTask -TaskName {quote(task)} -Action $action -Principal $principal -Settings $settings -Force | Out-Null; Start-ScheduledTask -TaskName {quote(task)}")
                try:
                    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],
                        capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception:
                    write_json(path/'launch.json',{'at':0,'material':material_id,'error':'scheduler_start_failed'})
                    raise
                write_json(path/'launch.json',{'at':time.time(),'scheduled_task':task,'material':material_id})
            else:
                flags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
                with (path/'worker.log').open('ab') as log:
                    child=subprocess.Popen([self.config['python'],'-u',str(Path(__file__).with_name('reaction_produce.py')),'--job',str(path/'job.json')],
                        stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=flags,close_fds=True,
                        env={**os.environ,'PYTHONUTF8':'1'})
                write_json(path/'launch.json',{'at':time.time(),'pid':child.pid,'material':material_id})
        return self.status(job_id)

    def status(self,job_id):
        path=self.folder(job_id)
        if not (path/'job.json').exists():raise ValueError('Unknown job')
        job=json.loads((path/'job.json').read_text(encoding='utf-8'))
        manifest=json.loads((path/'production.json').read_text(encoding='utf-8')) if (path/'production.json').exists() else {}
        viewed=json.loads((path/'viewing'/'viewing-state.json').read_text(encoding='utf-8')) if (path/'viewing'/'viewing-state.json').exists() else {}
        running=self.active(path)
        phase=manifest.get('phase','starting')
        launch=path/'launch.json'
        if running and launch.exists() and (not (path/'production.json').exists() or (path/'production.json').stat().st_mtime<json.loads(launch.read_text(encoding='utf-8'))['at']):phase='starting'
        if not running and phase not in ('complete','failed'):phase='interrupted'
        consumed={e.get('control_id') for e in viewed.get('events',[])}
        pending=[json.loads(p.read_text(encoding='utf-8')) for p in (path/'controls').glob('*.json')]
        return {'job_id':job_id,'phase':phase,'running':running,'viewed_seconds':viewed.get('cursor',0),'source_seconds':job['seconds'],
                'speech_count':len(viewed.get('playbacks',[])),'pause_count':len(viewed.get('pauses',[])),
                'observation_mode':'audiovisual_event_units' if viewed.get('input',{}).get('attention_version')==3 else 'legacy',
                'deliberations':sum(bool(e.get('deliberated')) for e in viewed.get('events',[])),
                'video':manifest.get('video') if phase=='complete' else None,'error':manifest.get('error') if phase=='failed' else None,
                'pending_controls':[{'id':p['id'],'action':p['action'],'status':'queued' if phase in ('starting','viewing','interrupted') else 'not_applied'} for p in pending if p['id'] not in consumed],
                'controls':[{'id':e['control_id'],'source':e['cursor'],'tool_result':e.get('replay_tool_result') or e.get('tool_result')} for e in viewed.get('events',[]) if e.get('control_id')]}

    def observation(self,job_id):
        path=self.folder(job_id)/'viewing'/'viewing-state.json'
        if not path.exists():return {'viewed_seconds':0,'note':'No observations yet'}
        s=json.loads(path.read_text(encoding='utf-8'));recent=s['events'][-5:]
        return {'viewed_seconds':s['cursor'],'plot_memory':s.get('plot_memory',''),'note':'Only observed material. Actor interpretations may be wrong; no future frames.',
                'recent':[{k:e.get(k) for k in ('cursor','story','interest','text','delivery','control_id')} for e in recent]}

    def control(self,job_id,action,topic='',seconds=5):
        path=self.folder(job_id)
        with self.lock,exclusive_job(self.root/'.manager.lock'):
            status=self.status(job_id)
            if not status['running'] or status['phase'] not in ('starting','viewing'):raise ValueError('Job is not currently viewing')
            if action=='pause_analysis' and (not isinstance(topic,str) or not 1<=len(topic.strip())<=500):raise ValueError('Describe the question worth pausing for')
            if action=='replay' and (isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 1<=seconds<=10):raise ValueError('Replay 1 to 10 already-seen seconds')
            if action not in ('pause_analysis','replay'):raise ValueError('Unknown control')
            folder=path/'controls';folder.mkdir(exist_ok=True)
            request={'id':str(time.time_ns())+'-'+uuid.uuid4().hex[:8],'action':action,'topic':topic,'seconds':seconds,'requested_after':status['viewed_seconds']}
            write_json(folder/(request['id']+'.json'),request)
            return {'queued':True,'control_id':request['id'],'requested_after':status['viewed_seconds'],'note':'Applied at next safe observation boundary. Analysis resumes automatically after speech; check status for receipt.'}


def register_reaction_tools(mcp,config_path):
    jobs=ReactionJobs(config_path)

    @mcp.tool()
    def reaction_catalog() -> str:
        """列出可陪看的已授权素材及制作任务。新任务先查这里，不读取未来剧情、不启动。"""
        return json.dumps(jobs.catalog(),ensure_ascii=False)

    @mcp.tool()
    def reaction_start(material_id:str,job_id:str,seconds:float=0,afterword:bool=True) -> str:
        """启动/恢复离线陪看制作，返回立即任务回执。只用素材ID；job_id用英文数字短横线。seconds=0看完整授权片段，可指定短样片。后台沿用你的人设/记忆/推理前缀，自主反应/暂停分析/表情动作，再配音、合成正常速度视频；afterword增加片尾感想。不会公开发布。同job_id重试不重复启动；用status看进度和成片。"""
        return json.dumps(jobs.start(material_id,job_id,seconds,afterword),ensure_ascii=False)

    @mcp.tool()
    def reaction_status(job_id:str) -> str:
        """查制作进度、暂停分析/回看回执和最终本地视频。running不代表完成；不另开任务。"""
        return json.dumps(jobs.status(job_id),ensure_ascii=False)

    @mcp.tool()
    def reaction_observation(job_id:str) -> str:
        """读取陪看已看到的剧情理解和最近反应。是可能误判的观察，非核实事实；不会透露后续。"""
        return json.dumps(jobs.observation(job_id),ensure_ascii=False)

    @mcp.tool()
    def reaction_pause_analysis(job_id:str,topic:str) -> str:
        """你决定当前问题值得暂停展开时调用。topic写想讨论的问题，后台只依据已看画面由你的人设生成分析并暂停原片声画，语音结束自动继续。不是每次发言都暂停；返回queued只是已排队，用status确认执行。"""
        return json.dumps(jobs.control(job_id,'pause_analysis',topic),ensure_ascii=False)

    @mcp.tool()
    def reaction_replay(job_id:str,seconds:float=5) -> str:
        """要求陪看者回看最近1至10秒已看内容，确认人物/字幕；不提前看剧情，不把回看重复插入成片。"""
        return json.dumps(jobs.control(job_id,'replay',seconds=seconds),ensure_ascii=False)

    return jobs


if __name__ == '__main__':
    import argparse
    from mcp.server.fastmcp import FastMCP
    parser = argparse.ArgumentParser(description='Local offline reaction tools for DSH')
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    server = FastMCP('reaction-production')
    register_reaction_tools(server, args.config)
    server.run(transport='stdio')
