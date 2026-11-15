"""Actor-owned viewing notes; optional revisions, lossless history, bounded injection."""
import copy
import json


def parse_updates(rows):
    if not isinstance(rows,list):raise ValueError('viewpoint_updates must be an array')
    seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('viewpoint update must be object')
        for key in ('id','text'):
            if not isinstance(row.get(key),str) or not row[key].strip():raise ValueError('viewpoint needs '+key)
        if len(row['id'])>120 or len(row['text'])>2000:raise ValueError('viewpoint too large')
        if row['id'] in seen:raise ValueError('duplicate viewpoint id')
        seen.add(row['id'])
        if row.get('status') not in ('active','settled','dropped'):raise ValueError('viewpoint status')
    return [{k:r[k] for k in ('id','text','status')} for r in rows]


def bootstrap_viewpoints(state):
    if 'viewpoints' in state:return
    state['viewpoints']={};state['viewpoint_history']=[]
    # Legacy resume preserves the last actor-authored attention; no invented summary.
    if state.get('attention'):
        apply_updates(state,[{'id':'legacy-attention','text':state['attention'],'status':'active'}],state['cursor'])


def apply_updates(state,rows,cursor):
    for row in parse_updates(rows):
        old=state['viewpoints'].get(row['id'])
        if old and all(old[k]==row[k] for k in ('text','status')):continue
        new={**row,'since':old['since'] if old else cursor,'updated_at':cursor}
        state['viewpoint_history'].append({'at':cursor,'before':copy.deepcopy(old),'after':copy.deepcopy(new)})
        state['viewpoints'][row['id']]=new


def viewpoint_context(state,budget=4500):
    result={'note':'你的私人观看看法，可能有误，不是剧情事实或发言任务；未更新的仍保留，可修正或放下。',
            'notes':[],'recent_changes':[],'omitted':0}
    rows=sorted(state['viewpoints'].values(),key=lambda x:(x['status']=='active',x['updated_at']),reverse=True)
    def fits():return len(json.dumps(result,ensure_ascii=False))<=budget
    for row in rows:
        result['notes'].append(copy.deepcopy(row))
        if not fits():result['notes'].pop();result['omitted']+=1
    # Include actual before/after changes when budget permits, never model-written summaries.
    for change in reversed(state['viewpoint_history']):
        if not change['before']:continue
        result['recent_changes'].append(copy.deepcopy(change))
        if not fits():result['recent_changes'].pop();break
    return result
