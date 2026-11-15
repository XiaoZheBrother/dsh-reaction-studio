"""Versioned evidence graph for viewing. No character, plot or speech policies.

Supported means evidence-backed model judgment, not externally certified truth.
Raw observations and superseded inferences are retained independently.
"""
import copy
import json
import math

KINDS = {'visual', 'voice', 'subject', 'utterance', 'action', 'mode'}
RELATIONS = {
    'performed_by': ({'action'}, {'visual'}),
    'affects': ({'action'}, {'visual'}),
    'voiced_by': ({'utterance'}, {'voice'}),
    'spoken_by': ({'utterance'}, {'visual'}),
    'thought_by': ({'utterance'}, {'subject'}),
    'first_person': ({'utterance'}, {'subject'}),
    'embodied_as': ({'subject'}, {'visual'}),
    'heard_by': ({'utterance'}, {'visual'}),
    'delivery': ({'utterance'}, {'mode'}),
}
BASES = {'observation', 'cooccurrence', 'continuity', 'response', 'self_identification', 'inference'}


def empty_graph():
    return {'schema': 1, 'evidence': {}, 'nodes': {}, 'links': {}, 'history': [], 'cursor': 0}


def _time(value, cursor):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= cursor:
        raise ValueError('Evidence time must be finite and already viewed')


def _ids(value):
    if not isinstance(value, list) or any(not isinstance(i, str) or not i for i in value):
        raise ValueError('Expected array of IDs')
    return list(dict.fromkeys(value))


def _sources(graph, ids, cursor):
    ids = _ids(ids)
    for key in ids:
        if key not in graph['evidence']:
            raise ValueError('Unknown evidence ID: '+key)
        _time(graph['evidence'][key]['available_at'], cursor)
    return ids


def _record(graph, section, row, cursor):
    old = graph[section].get(row['id'])
    if old:
        graph['history'].append({'section': section, 'superseded_at': cursor, 'record': copy.deepcopy(old)})
    row['revision'] = (old or {}).get('revision', 0)+1
    row['updated_at'] = cursor
    graph[section][row['id']] = row


def apply_graph(previous, evidence, delta, cursor):
    """Atomic copy-on-write update; revisions invalidate dependent conclusions."""
    graph = copy.deepcopy(previous or empty_graph())
    _time(cursor, cursor)
    if cursor < graph['cursor']:
        raise ValueError('Cannot overwrite a later checkpoint with an earlier view')
    for raw in evidence:
        row = copy.deepcopy(raw)
        if not isinstance(row.get('id'), str) or row.get('modality') not in ('visual', 'audio', 'text'):
            raise ValueError('Invalid evidence identity/modality')
        _time(row.get('at'), cursor); _time(row.get('available_at'), cursor)
        if row['at'] > row['available_at']:
            raise ValueError('Evidence cannot precede its source timestamp')
        if row['id'] in graph['evidence'] and graph['evidence'][row['id']] != row:
            raise ValueError('Raw evidence is immutable')
        graph['evidence'][row['id']] = row
    if not isinstance(delta, dict):
        raise ValueError('Graph delta must be an object')
    pending_nodes = delta.get('nodes', [])
    if not isinstance(pending_nodes, list) or len({r.get('id') for r in pending_nodes}) != len(pending_nodes):
        raise ValueError('nodes must be an array with unique IDs')
    for raw in pending_nodes:
        row = copy.deepcopy(raw)
        if not isinstance(row.get('id'), str) or not row['id'] or row.get('kind') not in KINDS:
            raise ValueError('Invalid typed node')
        if not isinstance(row.get('label'), str) or not 0 < len(row['label']) <= 120:
            raise ValueError('Node label required, <=120 characters')
        row['sources'] = _sources(graph, row.get('sources'), cursor)
        if not row['sources']:
            raise ValueError('Node needs observed evidence')
        old = graph['nodes'].get(row['id'])
        if old and old['kind'] != row['kind']:
            raise ValueError('Cannot merge voice, body, subject or event node types')
        if type(row.get('reidentify', False)) is not bool:
            raise ValueError('reidentify must be boolean')
        # Descriptive updates (pose, additional evidence) do not change identity.
        # A corrected event/transcript or explicit re-identification does.
        changed = old and (row.get('reidentify', False) or
                           (row['kind'] in ('utterance','action') and row['label'] != old['label']))
        row['identity_revision'] = (old or {}).get('identity_revision', 1) + int(bool(changed))
        _record(graph, 'nodes', row, cursor)
    pending = delta.get('links', [])
    if not isinstance(pending, list):
        raise ValueError('links must be an array')
    if len({r.get('id') for r in pending}) != len(pending):
        raise ValueError('Duplicate link update in one batch')
    updated = []
    for raw in pending:
        row = copy.deepcopy(raw)
        if not isinstance(row.get('id'), str) or not row['id']:
            raise ValueError('Link ID required')
        predicate = row.get('predicate')
        if predicate not in RELATIONS:
            raise ValueError('Unknown relation predicate')
        for key, allowed in zip(('subject', 'object'), RELATIONS[predicate]):
            if graph['nodes'].get(row.get(key), {}).get('kind') not in allowed:
                raise ValueError(f"{predicate}: {key}={row.get(key)} must reference an existing node of kind {sorted(allowed)}")
        if row.get('status') not in ('supported', 'tentative', 'rejected') or row.get('basis') not in BASES:
            raise ValueError('Invalid relationship status/basis')
        if not isinstance(row.get('reason'), str) or not row['reason']:
            raise ValueError('Relation reason required')
        row['support'] = _sources(graph, row.get('support', []), cursor)
        row['against'] = _sources(graph, row.get('against', []), cursor)
        if not row['support'] and not row['against']:
            raise ValueError('Relationship needs evidence, not a previous summary')
        row['depends_on'] = _ids(row.get('depends_on', []))
        # Same-time presence is not a speaker/subject bridge, regardless of label.
        if row['status'] == 'supported' and (not row['support'] or row['against']):
            row['status'] = 'needs_review'
        if row['status'] == 'supported' and row['basis'] == 'cooccurrence':
            row['status'] = 'tentative'
        _record(graph, 'links', row, cursor)
        updated.append(row['id'])
    def visit(key, stack):
        if key not in graph['links']:
            raise ValueError('Unknown dependency: '+key)
        if key in stack:
            raise ValueError('Cyclic relationship dependencies')
        for dep in graph['links'][key]['depends_on']:
            visit(dep, stack | {key})
    for key in graph['links']:
        visit(key, set())
    for key in updated:
        row = graph['links'][key]
        row['dependency_versions'] = {d: graph['links'][d]['revision'] for d in row['depends_on']}
        row['node_versions'] = {n: graph['nodes'][n]['identity_revision'] for n in (row['subject'],row['object'])}
    changed = True
    while changed:
        changed = False
        for key, row in list(graph['links'].items()):
            if row['status'] in ('needs_review', 'rejected'):
                continue
            stale = [d for d, rev in row.get('dependency_versions', {}).items()
                     if graph['links'][d]['revision'] != rev or graph['links'][d]['status'] in ('needs_review', 'rejected')
                     or (row['status'] == 'supported' and graph['links'][d]['status'] != 'supported')]
            stale += [n for n, rev in row.get('node_versions', {}).items() if graph['nodes'][n]['identity_revision'] != rev]
            if stale:
                replacement = copy.deepcopy(row)
                replacement.update(status='needs_review', invalidated_by=stale)
                _record(graph, 'links', replacement, cursor)
                changed = True
    graph['cursor'] = cursor
    return graph


def graph_context(graph, cursor, char_budget=14000):
    """Derived projection: no free-form summary can promote unverified bindings."""
    if cursor != graph['cursor']:
        raise ValueError('Use the checkpoint at the requested viewing cursor')
    rows = sorted(graph['links'].values(), key=lambda r:r['updated_at'], reverse=True)
    result = {'viewed_through': cursor, 'nodes': [], 'links': [], 'omitted_links': 0,
              'note': 'supported is evidence-backed model judgment, not certified truth. Missing links stay unknown. Full versions/evidence are available through review_relation.'}
    chosen = {}
    for row in rows:
        deps, todo = {}, [row['id']]
        while todo:
            key = todo.pop()
            if key in deps: continue
            deps[key] = graph['links'][key]
            todo.extend(deps[key]['depends_on'])
        proposal = {**chosen, **deps}
        node_ids = {r[k] for r in proposal.values() for k in ('subject','object')}
        nodes = [graph['nodes'][k] for k in sorted(node_ids)]
        if len(json.dumps({'nodes':nodes,'links':list(proposal.values())},ensure_ascii=False)) <= char_budget:
            chosen = proposal
    node_ids = {r[k] for r in chosen.values() for k in ('subject','object')}
    # Simple visible actions/utterances do not require a complex relationship first.
    nodes = {k:graph['nodes'][k] for k in node_ids}
    for row in sorted(graph['nodes'].values(), key=lambda r:r['updated_at'], reverse=True):
        proposal = {**nodes, row['id']:row}
        if len(json.dumps({'nodes':list(proposal.values()),'links':list(chosen.values())},ensure_ascii=False)) <= char_budget:
            nodes = proposal
    result.update(nodes=list(nodes.values()), links=list(chosen.values()),
                  omitted_links=len(graph['links'])-len(chosen), omitted_nodes=len(graph['nodes'])-len(nodes))
    return result


def ingest_observation(previous, delta, cursor):
    """Quarantine malformed proposals without discarding independent observations.

    Never repair endpoints by guessing the intended actor. Valid dependency chains
    are installed in order; unresolved chains retain their original rejected data.
    """
    if not isinstance(delta, dict) or any(not isinstance(delta.get(k, []), list) for k in ('nodes','links')):
        raise ValueError('Observation requires nodes and links arrays')
    graph=copy.deepcopy(previous)
    rejected=[]
    seen=set()
    for row in delta.get('nodes',[]):
        try:
            if not isinstance(row,dict) or row.get('id') in seen:raise ValueError('Invalid or duplicate node')
            seen.add(row.get('id'))
            graph=apply_graph(graph,[],{'nodes':[row]},cursor)
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'section':'nodes','proposal':copy.deepcopy(row),'reason':str(exc)})
    pending=list(delta.get('links',[]));seen=set()
    while pending:
        waiting=[];progress=False
        for row in pending:
            try:
                if not isinstance(row,dict) or row.get('id') in seen:raise ValueError('Invalid or duplicate link')
                deps=_ids(row.get('depends_on',[]))
                if any(d not in graph['links'] for d in deps):
                    waiting.append(row);continue
                seen.add(row.get('id'))
                graph=apply_graph(graph,[],{'links':[row]},cursor);progress=True
            except (ValueError,KeyError,TypeError) as exc:
                rejected.append({'section':'links','proposal':copy.deepcopy(row),'reason':str(exc)})
        if not progress:
            rejected += [{'section':'links','proposal':copy.deepcopy(row),'reason':'Unresolved or cyclic dependency'} for row in waiting]
            break
        pending=waiting
    return graph,rejected


def review_relation(graph, references, cursor, span=12):
    """Read-only evidence lookup and targeted replay range, always in the past."""
    _time(cursor, graph['cursor'])
    if cursor != graph['cursor']:
        raise ValueError('Use the checkpoint at the requested viewing cursor')
    if type(span) not in (int, float) or not math.isfinite(span) or not 0 < span <= 30:
        raise ValueError('Review span must be within 30 seconds')
    references = _ids(references)
    sources, links, nodes, todo = set(), {}, {}, list(references)
    while todo:
        key = todo.pop()
        if key in links or key in nodes or key in sources: continue
        if key in graph['links']:
            row = graph['links'][key]; links[key] = row
            todo += row['depends_on']+[row['subject'],row['object']]
            sources.update(row['support']+row['against'])
        elif key in graph['nodes']:
            row = graph['nodes'][key]; nodes[key] = row; sources.update(row['sources'])
        elif key in graph['evidence']:
            sources.add(key)
        else:
            raise ValueError('Unknown review reference: '+key)
    evidence = [graph['evidence'][k] for k in sorted(sources) if graph['evidence'][k]['available_at']<=cursor]
    windows = []
    for row in sorted(evidence,key=lambda x:x['at']):
        start,end = max(0,row['at']-span/2), min(cursor,row['at']+span/2)
        if windows and start <= windows[-1]['end'] and end-windows[-1]['start']<=span:
            windows[-1]['end']=end
        else: windows.append({'start':start,'end':end})
    return {'nodes':list(nodes.values()),'links':list(links.values()),'evidence':evidence,'replay_windows':windows,
            'history':[h for h in graph['history'] if h['record']['id'] in references and h['superseded_at']<=cursor]}


def check_claims(graph, text, claims):
    """Validate extracted claims and derive cross-modal bridges mechanically.

    This does not prove that a language-model auditor extracted every premise.
    """
    if not isinstance(claims,list): raise ValueError('claims must be an array')
    issues=[]
    active=[r for r in graph['links'].values() if r['status']=='supported']
    def edge(a,p,b): return any(r['subject']==a and r['predicate']==p and r['object']==b for r in active)
    def same_actor(utterance,action):
        actors=[r['object'] for r in active if r['subject']==action and r['predicate']=='performed_by']
        for actor in actors:
            if edge(utterance,'spoken_by',actor): return True
            subjects=[r['object'] for r in active if r['subject']==utterance and r['predicate'] in ('first_person','thought_by')]
            if any(edge(s,'embodied_as',actor) for s in subjects): return True
        return False
    for claim in claims:
        if not isinstance(claim, dict) or type(claim.get('same_actor', False)) is not bool:
            raise ValueError('Claim must be an object; same_actor must be boolean')
        if not isinstance(claim.get('quote'),str) or not claim['quote'] or claim['quote'] not in text:
            raise ValueError('Claim quote must occur exactly in proposed speech')
        if claim.get('kind') not in ('fact','hypothesis','feeling'):
            raise ValueError('Claim kind required')
        refs=_ids(claim.get('references',[]))
        required=_ids(claim.get('requires',[]))
        problems=[]
        for ref in refs:
            if ref not in graph['nodes']:problems.append('Unknown entity/event reference '+ref)
        for key in required:
            row=graph['links'].get(key)
            if not row or row['status'] in ('needs_review','rejected') or (claim['kind']=='fact' and row['status']!='supported'):
                problems.append('Relationship not supported: '+key)
        if claim['kind']=='fact':
            utterances=[r for r in refs if graph['nodes'].get(r,{}).get('kind')=='utterance']
            actions=[r for r in refs if graph['nodes'].get(r,{}).get('kind')=='action']
            if claim.get('same_actor',False):
                if not utterances or not actions: problems.append('same_actor needs utterance and action references')
                for u in utterances:
                    for a in actions:
                        if not same_actor(u,a):problems.append(f'No supported speaker/subject/body/action bridge between {u} and {a}')
        if problems:issues.append({'quote':claim['quote'],'reason':'; '.join(problems),'references':refs})
    return {'issues':issues,'claims':copy.deepcopy(claims)}


def check_public_claims(graph, text, claims):
    """Contradiction-only gate. Unknown is not false; opinions need no proof."""
    checked=check_claims(graph,text,claims)
    issues=[]
    for claim in claims:
        if claim['kind']!='fact':continue
        conflicts=[]
        for key in claim.get('requires',[]):
            row=graph['links'].get(key)
            if row and row['status']=='rejected' and row['against']:
                conflicts.append({'relation':key,'evidence':row['against'],'reason':row['reason']})
        for asserted in claim.get('asserted_relations',[]):
            if not isinstance(asserted,dict) or asserted.get('predicate') not in RELATIONS:
                raise ValueError('Invalid asserted relation')
            # Multiple people can perform a shared action. Only compare explicit
            # individual utterance/subject bindings; don't infer identities.
            if asserted['predicate'] not in ('spoken_by','thought_by','first_person','embodied_as'):continue
            alternatives=[r for r in graph['links'].values() if r['status']=='supported'
                          and r['subject']==asserted.get('subject') and r['predicate']==asserted['predicate']]
            if alternatives and all(r['object']!=asserted.get('object') for r in alternatives):
                conflicts += [{'relation':r['id'],'evidence':r['support'],'reason':r['reason']} for r in alternatives]
        if conflicts:issues.append({'quote':claim['quote'],'contradictions':conflicts})
    return {'issues':issues,'private_uncertainties':checked['issues'],'claims':copy.deepcopy(claims)}


def viewing_context(graph,cursor,char_budget=5500):
    """Actor sees remembered events, not the auditor's reasoning or schema."""
    projected=graph_context(graph,cursor,char_budget)
    nodes=[{k:r[k] for k in ('id','kind','label')} for r in projected['nodes'] if r['kind'] not in ('voice','mode')]
    ids={r['id'] for r in nodes}
    links=[{k:r[k] for k in ('id','subject','predicate','object','status')} for r in projected['links']
           if r['subject'] in ids and r['object'] in ids and r['status'] in ('supported','tentative')]
    return {'events_and_people':nodes,'working_connections':links,'history_is_partial':bool(projected['omitted_nodes'] or projected['omitted_links'])}
