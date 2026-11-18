"""多关系发现使用合成图和隔离目录，不改动正式图谱。"""
from copy import deepcopy
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from src.common.storage import read_json, write_json
from src.prediction.task import (PREDICTABLE_RELATIONS, discover_relations,
                                 predict_relations, validate_prediction_request)


def discovery_graph():
    nodes = [{'id': n, 'name': n, 'type': t} for n, t in
             [('p', 'Paper'), ('a', 'Method'), ('b', 'Method'), ('island', 'Component')]]
    edges = []
    def edge(source, relation, target):
        eid = f'{source}-{relation}-{target}'
        edges.append({'id': eid, 'source': source, 'relation': relation, 'target': target,
                      'evidence_ids': ['evidence'], 'paper_ids': ['p']})
    edge('p', 'PROPOSES', 'a')
    edge('p', 'PROPOSES', 'b')
    types = ['Component', 'Task', 'Representation', 'Dataset', 'Dataset', 'Metric']
    for i, (relation, kind) in enumerate(zip(PREDICTABLE_RELATIONS, types)):
        nodes.append({'id': f't{i}', 'name': f'Target {i}', 'type': kind})
        edge('b', relation, f't{i}')
    # Parallel relations must not double-count a node path.
    edge('b', 'EVALUATED_ON', 't3')
    edge('a', 'USES_METRIC', 't5')
    return {'version': 'v1', 'nodes': nodes, 'edges': edges,
            'evidence': [{'id': 'evidence', 'paper_id': 'p', 'page': 1, 'quote': 'Synthetic evidence'}]}


def test_discovery_six_relations_excludes_known_zero_and_wrong_types():
    graph = discovery_graph()
    result = discover_relations(graph)
    known = {(e['source'], e['relation'], e['target']) for e in graph['edges']}
    from src.common.models import RELATION_TYPES
    assert {c['relation'] for c in result['candidates']} == set(PREDICTABLE_RELATIONS)
    assert all((c['source_id'], c['relation'], c['target_id']) not in known for c in result['candidates'])
    types = {n['id']: n['type'] for n in graph['nodes']}
    for c in result['candidates']:
        assert c['source_id'] != c['target_id']
        assert types[c['source_id']] in RELATION_TYPES[c['relation']][0]
        assert types[c['target_id']] in RELATION_TYPES[c['relation']][1]
        assert c['score'] > 0 and c['target_id'] != 'island'
    a_component = next(c for c in result['candidates'] if c['source_id'] == 'a' and c['relation'] == 'USES_COMPONENT')
    # a-p-b-t0 and a-t5-b-t0 each contribute .5.
    assert a_component['score'] == 1
    assert a_component['path_count'] == 2
    assert len(a_component['paths']) == 2
    assert all(p['evidence_ids'] == ['evidence'] for p in a_component['paths'])


def test_single_equals_full_scan_and_relation_filter():
    graph = discovery_graph()
    all_rows = discover_relations(graph)['candidates']
    assert discover_relations(graph, 'a')['candidates'] == [c for c in all_rows if c['source_id'] == 'a']
    assert discover_relations(graph, 'a', ['USES_COMPONENT'])['candidates'] == [
        c for c in all_rows if c['source_id'] == 'a' and c['relation'] == 'USES_COMPONENT']
    assert discover_relations(graph, 'a', ['USES_COMPONENT', 'USES_COMPONENT'])['scope']['relation_types'] == ['USES_COMPONENT']


def test_parallel_edges_count_once_and_preserve_directions():
    graph = discovery_graph()
    c = next(c for c in discover_relations(graph, 'p')['candidates'] if c['relation'] == 'EVALUATED_ON' and c['target_id'] == 't3')
    assert c['score'] == 1 and c['path_count'] == 1
    assert len(c['paths'][0]['steps'][-1]) == 2
    altered = deepcopy(graph)
    altered['edges'].reverse()
    assert discover_relations(altered)['candidates'] == discover_relations(graph)['candidates']
    altered['edges'].append({'id': 'citation', 'source': 'a', 'target': 't0', 'relation': 'CITES'})
    assert discover_relations(altered)['candidates'] == discover_relations(graph)['candidates']


def test_top_ten_ties_and_five_explanations():
    graph = discovery_graph()
    for i in range(12):
        graph['nodes'].append({'id': f'c{i:02}', 'name': f'Component {i}', 'type': 'Component'})
        graph['edges'].append({'id': f'edge{i}', 'source': 'b', 'relation': 'USES_COMPONENT', 'target': f'c{i:02}'})
    rows = discover_relations(graph, 'a', ['USES_COMPONENT'])['candidates']
    assert len(rows) == 10
    assert [r['target_id'] for r in rows] == [f'c{i:02}' for i in range(10)]
    for i in range(8):
        graph['nodes'].append({'id': f'h{i}', 'name': 'hub', 'type': 'Paper'})
        for target in ['a', 'b']:
            graph['edges'].append({'id': f'h{i}-{target}', 'source': f'h{i}', 'target': target, 'relation': 'PROPOSES'})
    row = discover_relations(graph, 'a', ['USES_COMPONENT'])['candidates'][0]
    assert row['path_count'] > 5 and len(row['paths']) == 5


@pytest.mark.parametrize('source,relations', [('missing', None), ('t0', None), ('a', []), ('a', ['CITES']), ('p', ['TRAINED_ON'])])
def test_reject_invalid_request(source, relations):
    with pytest.raises(ValueError):
        validate_prediction_request(discovery_graph(), source, relations)


def test_empty_candidates():
    graph = discovery_graph()
    graph['edges'] = []
    result = discover_relations(graph)
    assert result['candidates'] == []
    assert result['context'] == {'nodes': [], 'edges': [], 'evidence': []}


def test_persistence_and_web_dispatch(workspace):
    data, exp = workspace
    graph = discovery_graph()
    write_json(data / 'graph_snapshot.json', graph)
    progress = []
    result = predict_relations('a', progress=lambda *args: progress.append(args))
    assert read_json(exp / 'relation_prediction.json') == result
    assert progress[-1][1:] == (1, 1)
    with TestClient(app) as client:
        for body in [{'source_id': 'missing'}, {'relation_types': ['CITES']}, {'relation_types': []}]:
            response = client.post('/api/run', json={'stage': 'relation_predict', **body})
            assert response.status_code == 400
        response = client.post('/api/run', json={'stage': 'relation_predict', 'source_id': 'p'})
        assert response.status_code == 200
        job_id = response.json()['id']
        for _ in range(100):
            job = next(j for j in client.get('/api/jobs').json() if j['id'] == job_id)
            if job['status'] in ['complete', 'failed']:
                break
            time.sleep(.03)
        assert job['status'] == 'complete', job
        assert job['completed'] == job['total'] == 1
        saved = client.get('/api/state').json()['results']['relation_prediction']
        assert saved['scope']['source_id'] == 'p'
        assert saved['graph_version'] == 'v1'
        graph['version'] = 'v2'
        write_json(data / 'graph_snapshot.json', graph)
        state = client.get('/api/state').json()
        assert state['graph']['version'] != state['results']['relation_prediction']['graph_version']


def test_failed_scan_preserves_last_success(workspace, monkeypatch):
    import backend.app as backend
    data, exp = workspace
    write_json(data / 'graph_snapshot.json', discovery_graph())
    saved = predict_relations('a')
    def fail_scan(**kwargs):
        raise RuntimeError('synthetic scan failure')
    monkeypatch.setattr(backend, 'predict_relations', fail_scan)
    with TestClient(app) as client:
        response = client.post('/api/run', json={'stage': 'relation_predict'})
        assert response.status_code == 200
        for _ in range(100):
            job = next(j for j in client.get('/api/jobs').json() if j['id'] == response.json()['id'])
            if job['status'] in ['complete', 'failed']:
                break
            time.sleep(.03)
        assert job['status'] == 'failed' and job['error'] == 'synthetic scan failure'
        assert client.get('/api/state').json()['results']['relation_prediction'] == saved
        assert read_json(exp / 'relation_prediction.json') == saved
