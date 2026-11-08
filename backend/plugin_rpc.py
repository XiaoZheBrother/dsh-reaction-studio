"""One bounded local DSH tool call; production workers have independent ownership."""
import argparse
import json
import sys
from reaction_mcp import ReactionJobs

def dispatch(jobs, action, args):
    if action == 'catalog': return jobs.catalog()
    if action == 'start': return jobs.start(args['material_id'], args['job_id'], args.get('seconds',0), args.get('afterword',True))
    if action == 'status': return jobs.status(args['job_id'])
    if action == 'observation': return jobs.observation(args['job_id'])
    if action == 'pause_analysis': return jobs.control(args['job_id'],'pause_analysis',args['topic'])
    if action == 'replay': return jobs.control(args['job_id'],'replay',seconds=args.get('seconds',5))
    raise ValueError('Unsupported tool')

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    options=parser.parse_args()
    try:
        request=json.loads(sys.stdin.read(20000))
        result=dispatch(ReactionJobs(options.config),request['action'],request.get('args',{}))
    except (ValueError, KeyError, OSError):
        result={'error':'请求或本地配置无效；请检查素材 ID、任务 ID、路径和依赖。'}
    print(json.dumps(result,ensure_ascii=False))
