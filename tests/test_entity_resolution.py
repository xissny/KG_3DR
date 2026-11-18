"""实体合并使用隔离教学语料与模拟模型，原始证据和人工审核不可丢失。"""
from copy import deepcopy
import json
from itertools import combinations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from src.common.identity import canonical_name
from src.common.storage import read_json, write_json
from src.review import resolution as er
from src.review.service import validate_facts


def add_variant(data):
    if not (data / 'aliases.json').exists():
        write_json(data / 'aliases.json', {})
    path = data / 'candidates/P001.json'
    rows = read_json(path)
    row = deepcopy(rows[1])
    row['id'] = 'F_alias_resolution'
    row['candidate']['object']['name'] = 'global attn'
    row['history'] = [{'note': 'original history'}]
    rows.append(row)
    write_json(path, rows)
    return row


def fake_chat(messages, purpose, force=False):
    context = json.loads(messages[-1]['content'])
    by_name = {e['name']: e for e in context['entities']}
    groups = []
    if 'global attn' in by_name and 'Global attention' in by_name:
        groups = [{'member_ids': [by_name[n]['id'] for n in ('global attn', 'Global attention')],
                   'canonical_name': 'Global attention', 'reason': '缩写与全称，关系和证据上下文一致'}]
    return {'data': {'groups': groups}, 'model': 'mock-model', 'cache_key': 'mock'}


def detected(workspace, monkeypatch):
    data, _ = workspace
    add_variant(data)
    monkeypatch.setattr(er, 'chat_json', fake_chat)
    er.detect_entities()
    view = er.overview()
    assert len(view['suggestions']) == 1
    return data, view, view['suggestions'][0]


def payload(view, row, action='confirm', **changes):
    return dict(revision=view['revision'], action=action, member_ids=row['member_ids'],
                canonical_name='Global Attention', reviewer='测试审核者', note='已核对') | changes


def test_catalogue_approved_included_only_and_six_types(workspace):
    data, _ = workspace
    add_variant(data)
    rows = read_json(data / 'candidates/P001.json')
    rows[-1]['status'] = 'pending'
    write_json(data / 'candidates/P001.json', rows)
    entities = er.catalogue()
    assert {e['type'] for e in entities} <= set(er.TYPES)
    assert not any(e['name'] == 'global attn' for e in entities)
    papers = read_json(data / 'papers.json')
    papers[0]['included'] = False
    write_json(data / 'papers.json', papers)
    assert all(ev['paper_id'] != 'P001' for e in er.catalogue() for ev in e['evidence'])


def test_confirm_preserves_evidence_and_graph_requires_explicit_import(workspace, monkeypatch):
    data, view, row = detected(workspace, monkeypatch)
    before = {p.name: p.read_bytes() for p in (data / 'candidates').glob('*.json')}
    official = (data / 'graph_snapshot.json').read_bytes()
    validate_facts()
    old = read_json(data / 'approved_graph.json')
    assert len(old['edges']) == 61
    with TestClient(app) as client:
        response = client.put('/api/entity-resolution/' + row['id'], json=payload(view, row))
        assert response.status_code == 200, response.text
        saved = response.json()['suggestions'][0]
        assert saved['status'] == 'confirmed' and saved['reviewer'] == '测试审核者'
        assert saved['original']['canonical_name'] == 'Global attention'
        assert saved['alias_changes']['after']
        assert client.put('/api/entity-resolution/' + row['id'], json=payload(view, row)).status_code == 409
    aliases = read_json(data / 'aliases.json')
    assert canonical_name('Component', 'global attn', aliases) == 'Global Attention'
    assert canonical_name('Component', 'Global attention', aliases) == 'Global Attention'
    assert (data / 'graph_snapshot.json').read_bytes() == official
    validate_facts()
    graph = read_json(data / 'approved_graph.json')
    assert len(graph['edges']) == 60 and len(graph['evidence']) == 61
    assert any('F_alias_resolution' in edge['evidence_ids'] and len(edge['evidence_ids']) == 2 for edge in graph['edges'])
    assert before == {p.name: p.read_bytes() for p in (data / 'candidates').glob('*.json')}


def test_draft_editing_reject_and_no_repeat(workspace, monkeypatch):
    data, view, row = detected(workspace, monkeypatch)
    original_aliases = (data / 'aliases.json').read_bytes()
    view = er.save_review(row['id'], er.ResolutionUpdate(**payload(view, row, 'draft', reviewer='', canonical_name='自定义名称')))
    assert er.document()['suggestions'][0]['status'] == 'draft'
    assert (data / 'aliases.json').read_bytes() == original_aliases
    er.save_review(row['id'], er.ResolutionUpdate(**payload(view, row, 'reject')))
    er.detect_entities(force=True)
    assert len(er.document()['suggestions']) == 1
    assert (data / 'aliases.json').read_bytes() == original_aliases


def test_stale_input_revision_and_evidence_changes(workspace, monkeypatch):
    data, view, row = detected(workspace, monkeypatch)
    rows = read_json(data / 'candidates/P001.json')
    rows[-1]['status'] = 'rejected'
    write_json(data / 'candidates/P001.json', rows)
    with TestClient(app) as client:
        assert client.put('/api/entity-resolution/' + row['id'], json=payload(view, row)).status_code == 409
        current = client.get('/api/entity-resolution').json()
        assert current['suggestions'][0]['stale']
        assert client.put('/api/entity-resolution/' + row['id'], json=payload(current, row)).status_code == 409


def test_validation_and_busy_guard(workspace, monkeypatch):
    data, view, row = detected(workspace, monkeypatch)
    other = next(e for e in view['entities'] if e['type'] == 'Task')
    with TestClient(app) as client:
        url = '/api/entity-resolution/' + row['id']
        for edits in [dict(reviewer='  '), dict(canonical_name='  '), dict(member_ids=[row['member_ids'][0]]),
                      dict(member_ids=[row['member_ids'][0]]*2), dict(member_ids=[row['member_ids'][0], other['id']])]:
            assert client.put(url, json=payload(view, row, **edits)).status_code in (400, 422)
        write_json(data / 'jobs/active.json', {'id': 'active', 'status': 'running', 'created_at': 'now'})
        # Startup recovery is already finished, so this represents an active worker.
        assert client.put(url, json=payload(view, row)).status_code == 409


def test_alias_chains_target_collision_and_adding_member(workspace, monkeypatch):
    data, view, row = detected(workspace, monkeypatch)
    aliases = read_json(data / 'aliases.json')
    aliases.update({'Component:GA': 'old abbreviation', 'Component:old abbreviation': 'global attn',
                    'Task:keep': 'Separate task'})
    write_json(data / 'aliases.json', aliases)
    view = er.overview()
    selected = [e for e in view['entities'] if e['id'] in row['member_ids']]
    external = next(e for e in view['entities'] if e['type'] == 'Component' and e['id'] not in row['member_ids'])
    with pytest.raises(ValueError, match='组外'):
        er.merged_aliases(view['entities'], selected, external['name'])
    updated = er.merged_aliases(view['entities'], selected, 'GA')
    assert canonical_name('Component', 'Global attention', updated) == 'GA'
    assert canonical_name('Component', 'old abbreviation', updated) == 'GA'
    assert updated['Task:keep'] == 'Separate task'
    ids = [*row['member_ids'], external['id']]
    view = er.save_review(row['id'], er.ResolutionUpdate(**payload(view, row, 'draft', member_ids=ids)))
    assert len(view['suggestions'][0]['members']) == 3
    # Removing an added member is supported by saving the original two IDs again.
    er.save_review(row['id'], er.ResolutionUpdate(**payload(view, row, 'draft')))
    assert len(er.document()['suggestions'][0]['members']) == 2


def test_all_pairs_compared_across_batches(workspace, monkeypatch):
    members = [{'id': str(i), 'type': 'Method', 'name': str(i), 'names': [str(i)], 'evidence': []} for i in range(45)]
    monkeypatch.setattr(er, 'catalogue', lambda: members)
    compared = set()
    def chat(messages, **kwargs):
        ids = [e['id'] for e in json.loads(messages[-1]['content'])['entities']]
        compared.update(frozenset(pair) for pair in combinations(ids, 2))
        return {'data': {'groups': []}}
    monkeypatch.setattr(er, 'chat_json', chat)
    er.detect_entities()
    assert len(compared) == 45*44//2
    assert er.document()['run']['total'] == 6


def test_invalid_model_partial_retry_and_empty(workspace, monkeypatch):
    data, _ = workspace
    add_variant(data)
    calls = []
    def broken(messages, **kwargs):
        kind = json.loads(messages[-1]['content'])['type']
        calls.append(kind)
        if kind == 'Component':
            return {'data': {'groups': 'invalid envelope'}}
        return fake_chat(messages, **kwargs)
    monkeypatch.setattr(er, 'chat_json', broken)
    with pytest.raises(ValueError, match='批检测失败'):
        er.detect_entities()
    assert er.document()['run']['status'] == 'partial'
    assert not er.document()['suggestions']
    calls.clear()
    def retry(messages, **kwargs):
        calls.append(json.loads(messages[-1]['content'])['type'])
        return fake_chat(messages, **kwargs)
    monkeypatch.setattr(er, 'chat_json', retry)
    er.detect_entities()
    assert calls == ['Component']
    assert len(er.document()['suggestions']) == 1
    monkeypatch.setattr(er, 'catalogue', lambda: [])
    er.detect_entities()
    assert er.document()['run']['total'] == 0


def test_overlap_is_not_transitively_merged(workspace, monkeypatch):
    data, _ = workspace
    add_variant(data)
    def overlapping(messages, **kwargs):
        entities = json.loads(messages[-1]['content'])['entities']
        groups = []
        if entities[0]['type'] == 'Component':
            groups = [{'member_ids': [a['id'], b['id']], 'canonical_name': a['name'], 'reason': '待人工核对'}
                      for a, b in zip(entities, entities[1:])]
        return {'data': {'groups': groups}}
    monkeypatch.setattr(er, 'chat_json', overlapping)
    aliases = (data / 'aliases.json').read_bytes()
    er.detect_entities()
    view = er.overview()
    assert len(view['suggestions']) >= 2
    assert (data / 'aliases.json').read_bytes() == aliases
    first = view['suggestions'][0]
    er.save_review(first['id'], er.ResolutionUpdate(**payload(view, first, canonical_name='Merged component')))
    assert any(r['stale'] for r in er.overview()['suggestions'] if r['id'] != first['id'])


def test_transaction_failure_rolls_back_aliases_and_review(workspace, monkeypatch):
    data, view, row = detected(workspace, monkeypatch)
    before = {name: (data / name).read_bytes() for name in ['aliases.json', 'entity_resolution.json']}
    from pathlib import Path
    original = Path.replace
    def failing_replace(path, target):
        if target == data / 'entity_resolution.json':
            raise OSError('simulated disk failure')
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', failing_replace)
    with pytest.raises(OSError, match='simulated'):
        er.save_review(row['id'], er.ResolutionUpdate(**payload(view, row)))
    assert before == {name: (data / name).read_bytes() for name in before}
    assert next((data / 'entity_resolution_backups').glob('*/manifest.json')).exists()


@pytest.mark.parametrize('invalid', [
    {'member_ids': ['only-one'], 'canonical_name': '单实体', 'reason': '无匹配'},
    {'member_ids': [], 'canonical_name': '空组', 'reason': '无匹配'},
    {'member_ids': ['invented', 'also invented'], 'canonical_name': '未知实体', 'reason': '错误'},
    {'member_ids': ['repeated', 'repeated'], 'canonical_name': '重复实体', 'reason': '错误'},
    {'member_ids': None, 'canonical_name': '格式错误', 'reason': '错误'},
    None,
])
def test_invalid_group_does_not_discard_valid_groups(workspace, monkeypatch, invalid):
    data, _ = workspace
    add_variant(data)
    aliases = (data / 'aliases.json').read_bytes()
    def mixed(messages, **kwargs):
        response = fake_chat(messages, **kwargs)
        if json.loads(messages[-1]['content'])['type'] == 'Component':
            groups = response['data']['groups']
            broken = deepcopy(invalid)
            if isinstance(broken, dict) and broken.get('canonical_name') == '重复实体':
                broken['member_ids'] = [groups[0]['member_ids'][0]] * 2
            response['data']['groups'] = [broken, *groups]
        return response
    monkeypatch.setattr(er, 'chat_json', mixed)
    result = er.detect_entities()
    assert result['status'] == 'complete' and not result['errors']
    assert sum(w['ignored'] for w in result['warnings']) == 1
    assert len(er.document()['suggestions']) == 1
    assert er.document()['suggestions'][0]['status'] == 'pending'
    assert (data / 'aliases.json').read_bytes() == aliases
    # 已完成批次不会再调用模型，且提示在重试/刷新后保留。
    monkeypatch.setattr(er, 'chat_json', lambda *a, **kw: pytest.fail('completed batch called model again'))
    assert er.detect_entities()['warnings'] == result['warnings']


def test_old_partial_run_recovers_from_cached_singletons(workspace, monkeypatch):
    data, _ = workspace
    add_variant(data)
    calls = []
    def cached(messages, **kwargs):
        calls.append(kwargs.get('force'))
        response = fake_chat(messages, **kwargs)
        groups = response['data']['groups']
        if groups:
            singleton = deepcopy(groups[0])
            singleton['member_ids'] = singleton['member_ids'][:1]
            response['data']['groups'] = [singleton, groups[0]]
        return response
    write_json(data / 'entity_resolution.json', {'suggestions': [], 'run': {
        'input_revision': er.input_revision(er.catalogue()), 'status': 'partial',
        'finished_batches': [], 'errors': [{'error': 'old validation failure'}]}})
    monkeypatch.setattr(er, 'chat_json', cached)
    result = er.detect_entities()
    assert result['status'] == 'complete' and not result['errors']
    assert len(er.document()['suggestions']) == 1
    assert sum(w['ignored'] for w in result['warnings']) == 1
    assert calls and not any(calls)


def test_all_invalid_groups_complete_with_notice(workspace, monkeypatch):
    data, _ = workspace
    add_variant(data)
    def invalid(messages, **kwargs):
        entity = json.loads(messages[-1]['content'])['entities'][0]
        return {'data': {'groups': [{'member_ids': [entity['id']], 'canonical_name': entity['name'], 'reason': '没有同义项'}]}}
    monkeypatch.setattr(er, 'chat_json', invalid)
    result = er.detect_entities()
    assert result['status'] == 'complete' and not result['errors']
    assert not er.document()['suggestions']
    assert sum(w['ignored'] for w in result['warnings']) == result['total']
