"""Validate bundled design examples; no inference or ground-truth claims."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(ok, message):
    if not ok:
        raise ValueError(message)

def unique(items):
    ids = [x['id'] for x in items]
    check(len(ids) == len(set(ids)), 'Duplicate IDs')
    return set(ids)

def pointer(document, path):
    value = document
    for key in path.lstrip('/').split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value

def validate_scene(d):
    objects = unique(d['objects'])
    humans = unique(d['humans'])
    events = unique(d['events'])
    observations = unique(d['observations'])
    check(not objects & humans, 'Human must be outside objects')
    unique(d['relations'])
    for edge in d['relations']:
        check(edge['source'] in objects and edge['target'] in objects, 'Broken object edge')
    for obj in d['objects']:
        for effect in obj.get('Affordance', {}).get('effects', []):
            check(effect['object_id'] in objects, 'Broken effect')
        if 'Geometry' in obj:
            check(obj['Geometry']['pose']['frame_id'] in objects, 'Broken frame')
    for state in d['states']:
        check(state['object_id'] in objects, 'Broken state')
        check(state['start_ms'] >= 0 and (state['end_ms'] is None or state['end_ms'] > state['start_ms']), 'Invalid interval')
    for e in d['events']:
        check(e['time_ms'] >= 0, 'Negative time')
        if 'actor_id' in e:
            check(e['actor_id'] in humans and e['target_id'] in objects, 'Broken action')
    for o in d['observations']:
        check(o['actor_id'] in humans and o['related_event_id'] in events, 'Broken observation')
        check(0 <= o['start_ms'] < o['end_ms'], 'Invalid observation interval')
    i = d['interpretation']
    check(i['actor_id'] in humans and i['related_event_id'] in events and i['selected_action_id'] in events, 'Broken interpretation')
    check(set(i['observation_ids']) <= observations, 'Broken observation IDs')
    if 'decision_graph' not in d:
        return
    g = d['decision_graph']
    nodes = unique(g['nodes'])
    check(g['actor_id'] in humans, 'Unknown decision actor')
    unique(g['edges'])
    check(nodes == {'DP1', 'DP2', 'DP3', 'DP4', 'DP5'}, 'Invalid DPs')
    next_pairs = {(e['source'], e['target']) for e in g['edges'] if e['type'] == 'NEXT'}
    check(next_pairs == {(f'DP{i}', f'DP{i+1}') for i in range(1,5)}, 'Invalid NEXT')
    update_pairs = set()
    all_records = []
    records_by_id = {}
    latest = {}
    for e in g['edges']:
        check(e['source'] in nodes and e['target'] in nodes, 'Broken DP edge')
        if e['type'] != 'UPDATE':
            continue
        pair = (e['source'], e['target'])
        check(pair not in update_pairs, 'Duplicate UPDATE pair')
        update_pairs.add(pair)
        ts = [r['time_ms'] for r in e['records']]
        check(all(a < b for a,b in zip(ts,ts[1:])), 'Non-increasing records')
        for r in e['records']:
            check(r['id'] not in records_by_id, 'Duplicate record')
            records_by_id[r['id']] = (r, e)
            all_records.append(r)
            for ref in r['observation']['evidence_refs']:
                pointer(d, ref)
            for rule in r['inference']['matched_rules']:
                check(rule in {f'R{i}' for i in range(1,9)}, 'Unknown rule')
            primary = r['inference']['primary_rule']
            check(primary is None or primary in r['inference']['matched_rules'], 'Invalid primary rule')
            target = e['target']
            if target not in latest or r['time_ms'] > latest[target]['time_ms']:
                latest[target] = r
    for r in all_records:
        prev = r['previous_event_id']
        if prev:
            check(prev in records_by_id, 'Missing previous record')
            p, pe = records_by_id[prev]
            check(p['time_ms'] < r['time_ms'], 'Previous record must be earlier')
            check(pe['target'] == records_by_id[r['id']][1]['source'], 'UPDATE continuity')
    for n in g['nodes']:
        check(n['latest_event_id'] == latest.get(n['id'], {}).get('id'), 'Invalid latest reference')

if __name__ == '__main__':
    files = list(ROOT.rglob('*.json'))
    for path in files:
        json.loads(path.read_text(encoding='utf-8'))
    source = json.loads((ROOT/'examples/p4_cutting_error.source.json').read_text(encoding='utf-8'))
    integrated = json.loads((ROOT/'examples/p4_cutting_error.json').read_text(encoding='utf-8'))
    check(all(integrated[k] == v for k,v in source.items()), 'PDF fields changed')
    validate_scene(source)
    validate_scene(integrated)
    print(f'PASS: {len(files)} JSON files; PDF fields preserved; scene and decision references/times valid.')
