"""自动分类无需人工标签；模型响应均模拟，绝不调用付费API。"""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from src.classification import automatic as auto
from src.common.storage import read_json, write_json
from backend.app import app


def fake_chat(messages, purpose, force=False):
    payload = json.loads(messages[-1]['content'])
    if purpose.endswith(':taxonomy'):
        nodes = payload['entities']
        tasks = [n['id'] for n in nodes if n['type'] == 'Task']
        anchors = [n['id'] for n in nodes if n['type'] in ('Method', 'Component', 'Representation')]
        categories = []
        if tasks:
            categories.append({'dimension': 'task', 'name': '测试任务', 'definition': '虚构任务类别', 'entity_ids': tasks})
        if anchors:
            categories += [{'dimension': d, 'name': name, 'definition': '虚构类别', 'entity_ids': anchors[:10]} for d, name in [('topic', '三维几何'), ('method', '学习式方法')]]
        return {'data': {'categories': categories}, 'cache_key': 'taxonomy_test'}
    context = payload['paper']
    fact = context['facts'][0]
    assignments = [{'category_id': c['id'], 'explanation': '基于测试图谱事实归纳', 'fact_ids': [fact['id']],
                    'evidence_ids': [fact['evidence_ids'][0]]} for c in payload['categories'] if c['dimension'] in ('topic', 'method')]
    return {'data': {'assignments': assignments, 'limitations': '仅为测试推断'}, 'cache_key': 'paper_test'}


@pytest.fixture
def model(workspace, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only-key')
    monkeypatch.setattr(auto, 'chat_json', fake_chat)
    write_json(workspace[0] / 'labels.json', {})
    return workspace


def test_zero_manual_labels_batch_resume_and_subset(model, monkeypatch):
    data, exp = model
    first = auto.run_automatic_classification(['P001', 'P002'])
    assert first['status'] == 'complete'
    result = read_json(exp / 'automatic_classification.json')
    assert set(result['papers']) == {'P001', 'P002'}
    row = result['papers']['P001']
    assert {a['dimension'] for a in row['assignments']} == set(auto.DIMENSIONS)
    assert {a['source'] for a in row['assignments']} == {'direct', 'inferred'}
    assert row['context']['evidence'] and all(e['paper_id'] == 'P001' for e in row['context']['evidence'])
    assert read_json(data / 'labels.json') == {}
    def forbidden(*args, **kwargs):
        raise AssertionError('完整结果不应再次请求模型')
    monkeypatch.setattr(auto, 'chat_json', forbidden)
    auto.run_automatic_classification(['P001'])
    assert read_json(exp / 'automatic_classification.json')['papers']['P002'] == result['papers']['P002']


def test_shared_entities_and_cited_paper_do_not_transfer_ownership(workspace):
    graph = read_json(workspace[0] / 'graph_snapshot.json')
    ctx = auto.paper_context(graph, 'P001')
    method = next(f['target'] for f in ctx['facts'] if f['relation'] == 'PROPOSES')
    task = next(n['id'] for n in graph['nodes'] if n['type'] == 'Task')
    graph['evidence'].append({'id': 'foreign', 'paper_id': 'P002', 'page': 1, 'quote': 'foreign facts only'})
    graph['edges'].append({'id': 'foreign_fact', 'source': method, 'target': task, 'relation': 'SOLVES', 'evidence_ids': ['foreign'], 'paper_ids': ['P002']})
    # 即使是本篇引用到的另一篇论文，也不能借用对方的提出关系。
    graph['evidence'].append({'id': 'citation_quote', 'paper_id': 'P001', 'page': 1, 'quote': 'P002 proposes a method'})
    graph['edges'].append({'id': 'cited_fact', 'source': 'P002', 'target': method, 'relation': 'PROPOSES', 'evidence_ids': ['citation_quote'], 'paper_ids': ['P001']})
    context = auto.paper_context(graph, 'P001')
    assert not {'foreign_fact', 'cited_fact'} & {f['id'] for f in context['facts']}
    assert all(e['paper_id'] == 'P001' for e in context['evidence'])


def test_invalid_claims_unknown_categories_and_wrong_fact_evidence_rejected(model):
    graph = read_json(model[0] / 'graph_snapshot.json')
    taxonomy = auto.build_taxonomy(graph)
    context = auto.paper_context(graph, 'P001')
    first, second = context['facts'][:2]
    cid = taxonomy['categories'][0]['id']
    base = {'category_id': cid, 'explanation': '测试', 'fact_ids': [first['id']], 'evidence_ids': first['evidence_ids']}
    claims = [base, base | {'category_id': 'unknown'}, base | {'fact_ids': ['missing']},
              base | {'evidence_ids': ['foreign']}, base | {'evidence_ids': second['evidence_ids']}]
    accepted, rejected, _ = auto.validate_assignments({'assignments': claims}, context, taxonomy)
    assert len(accepted) == 1 and rejected == 4


def test_missing_key_preserves_direct_tasks_and_no_fake_metrics(workspace, monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    write_json(workspace[0] / 'labels.json', {})
    result = auto.run_automatic_classification(['P001'])
    assert result['status'] == 'partial'
    row = read_json(workspace[1] / 'automatic_classification.json')['papers']['P001']
    assert row['assignments'] and all(a['source'] == 'direct' for a in row['assignments'])
    assert row['missing_dimensions'] == ['topic', 'method']
    assert 'micro_f1' not in row and row['errors']


def test_single_paper_failure_preserves_previous_batch(model, monkeypatch):
    auto.run_automatic_classification(['P001'])
    def fail(messages, purpose, force=False):
        if purpose.endswith(':paper'):
            raise ValueError('模拟超时')
        return fake_chat(messages, purpose, force)
    monkeypatch.setattr(auto, 'chat_json', fail)
    auto.run_automatic_classification(['P002'])
    rows = read_json(model[1] / 'automatic_classification.json')['papers']
    assert rows['P001']['status'] == 'complete' and rows['P002']['status'] == 'partial'
    assert rows['P002']['assignments'] and rows['P002']['errors']


def test_reference_only_and_excluded_papers_cannot_be_classified(model):
    papers = read_json(model[0] / 'papers.json')
    papers[0]['included'] = False
    write_json(model[0] / 'papers.json', papers)
    with pytest.raises(ValueError):
        auto.run_automatic_classification(['P001'])
    with pytest.raises(ValueError):
        auto.run_automatic_classification(['paper_external'])
    assert len(auto.classification_overview()['papers']) == 11


def test_api_personal_corrections_separate_from_gold_and_version_guard(model):
    auto.run_automatic_classification(['P001'])
    data, exp = model
    gold = read_json(data / 'labels.json')
    with TestClient(app) as client:
        overview = client.get('/api/classification/automatic').json()
        cid = overview['taxonomy']['categories'][0]['id']
        paper = next(p for p in overview['papers'] if p['paper_id'] == 'P001')
        payload = {'category_ids': [cid], 'graph_version': overview['graph_version'],
                   'taxonomy_version': overview['taxonomy']['version'], 'paper_sha256': paper['sha256'], 'note': '自定义修订'}
        assert client.put('/api/classification/automatic/P001', json=payload).status_code == 200
        assert read_json(data / 'labels.json') == gold
        assert read_json(exp / 'automatic_classification.json')['papers']['P001']['assignments']
        assert client.put('/api/classification/automatic/P001', json=payload | {'graph_version': 'old'}).status_code == 400
        assert client.put('/api/classification/automatic/P001', json=payload | {'category_ids': ['unknown']}).status_code == 400
        query = {k: payload[k] for k in ['graph_version', 'taxonomy_version', 'paper_sha256']}
        assert client.delete('/api/classification/automatic/P001', params=query).status_code == 200
        assert read_json(exp / 'classification_corrections.json') == {}


def test_old_graph_results_visible_but_versions_differ(model):
    auto.run_automatic_classification(['P001'])
    graph = read_json(model[0] / 'graph_snapshot.json')
    graph['version'] = 'new_graph'
    write_json(model[0] / 'graph_snapshot.json', graph)
    overview = auto.classification_overview()
    assert overview['taxonomy_outdated']
    assert overview['result']['papers']['P001']['graph_version'] != overview['graph_version']


def test_taxonomy_rebuild_failure_keeps_existing_system(model, monkeypatch):
    old = auto.build_taxonomy()
    def fail(*args, **kwargs):
        raise ValueError('模拟更新失败')
    monkeypatch.setattr(auto, 'chat_json', fail)
    updated = auto.build_taxonomy(rebuild=True)
    assert updated['version'] == old['version']
    assert updated['last_rebuild_errors']
