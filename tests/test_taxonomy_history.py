"""类别历史使用临时目录；恢复不调用模型、不改动图谱和论文分类。"""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from src.classification import automatic as auto, history
from src.common.storage import read_json, write_json
from backend.app import app


def category(name, anchors, dimension='task', definition='测试类别'):
    return {'id': auto.category_id(dimension, name), 'dimension': dimension, 'name': name,
            'definition': definition, 'entity_ids': anchors, 'parent_id': None}


def taxonomy(categories, graph_version='graph_one'):
    return {'version': auto.taxonomy_version(categories), 'categories': categories, 'graph_version': graph_version,
            'source': 'deepseek', 'model': 'mock', 'errors': [], 'time': '2026-11-17T00:00:00+00:00'}


def test_legacy_baseline_and_immutable_history(workspace):
    _, exp = workspace
    original = taxonomy([category('深度估计', ['depth'])])
    write_json(exp / 'classification_taxonomy.json', original)
    saved = history.ensure_current_snapshot()
    path = history.snapshot_path(saved['snapshot_id'])
    before = path.read_bytes()
    assert history.ensure_current_snapshot() == saved
    assert len(history.history_list()['versions']) == 1
    newer = history.activate_taxonomy(taxonomy([category('几何估计', ['depth'])]))
    assert path.read_bytes() == before
    entries = history.history_list()['versions']
    assert len(entries) == 2
    assert entries[0]['is_current'] and entries[0]['previous_snapshot_id'] == saved['snapshot_id']
    assert newer['version'] != original['version']


def test_repeated_content_still_keeps_distinct_events(workspace):
    first = history.activate_taxonomy(taxonomy([category('深度', ['a'])]), 'create')
    second = history.activate_taxonomy(first, 'update')
    assert first['version'] == second['version']
    assert first['snapshot_id'] != second['snapshot_id']
    assert len(history.history_list()['versions']) == 2


def test_exact_diff_and_possible_merge_split_and_rename(workspace):
    old = taxonomy([category('单目深度', ['mono']), category('双目深度', ['stereo']), category('点图', ['point'])])
    new = taxonomy([category('深度估计', ['mono', 'stereo']), category('点图', ['point'], definition='新定义')])
    diff = history.compare_taxonomies(old, new)
    assert len(diff['added']) == 1 and len(diff['removed']) == 2
    assert diff['modified'][0]['fields'] == ['definition']
    assert len(diff['possible_merges']) == 1 and not diff['possible_renames']
    reverse = history.compare_taxonomies(new, old)
    assert len(reverse['possible_splits']) == 1
    renamed = history.compare_taxonomies(taxonomy([category('点图', ['point'])]), taxonomy([category('点映射', ['point'])]))
    assert len(renamed['possible_renames']) == 1
    unchanged = history.compare_taxonomies(old, old)
    assert unchanged['same_content'] and not unchanged['modified']


def test_restore_creates_event_guards_versions_and_preserves_data(workspace):
    data, exp = workspace
    graph = read_json(data / 'graph_snapshot.json')
    paper = read_json(data / 'papers.json')[0]
    first = history.activate_taxonomy(taxonomy([category('旧类别', ['a'])], graph['version']), 'create')
    old_snapshot_bytes = history.snapshot_path(first['snapshot_id']).read_bytes()
    second = history.activate_taxonomy(taxonomy([category('新类别', ['a'])], graph['version']))
    row = {'status': 'complete', 'paper_id': paper['paper_id'], 'paper_sha256': paper['sha256'], 'taxonomy_version': first['version'], 'graph_version': graph['version']}
    write_json(exp / 'automatic_classification.json', {'papers': {paper['paper_id']: row}})
    write_json(exp / 'classification_corrections.json', {paper['paper_id']: row})
    protected = [data / 'graph_snapshot.json', data / 'labels.json', exp / 'automatic_classification.json', exp / 'classification_corrections.json']
    before = {p: p.read_bytes() for p in protected}
    with pytest.raises(ValueError, match='已变化'):
        history.restore_taxonomy(first['snapshot_id'], 'wrong', graph['version'])
    with pytest.raises(ValueError, match='已变化'):
        history.restore_taxonomy(first['snapshot_id'], second['snapshot_id'], 'wrong_graph')
    restored = history.restore_taxonomy(first['snapshot_id'], second['snapshot_id'], graph['version'])
    assert restored['taxonomy']['version'] == first['version']
    assert restored['taxonomy']['snapshot_id'] not in {first['snapshot_id'], second['snapshot_id']}
    assert paper['paper_id'] in restored['impact']['valid_papers']
    assert len(restored['impact']['needs_classification']) == 11
    assert not restored['impact']['outdated_corrections']
    assert all(p.read_bytes() == contents for p, contents in before.items())
    assert history.snapshot_path(first['snapshot_id']).read_bytes() == old_snapshot_bytes
    entry = history.get_snapshot(restored['taxonomy']['snapshot_id'])
    assert entry['restored_from'] == first['snapshot_id'] and entry['action'] == 'restore'


def test_api_restore_and_path_validation(workspace):
    graph = read_json(workspace[0] / 'graph_snapshot.json')
    first = history.activate_taxonomy(taxonomy([category('旧类别', ['a'])], 'old_graph'), 'create')
    current = history.activate_taxonomy(taxonomy([category('新类别', ['b'])], graph['version']))
    with TestClient(app) as client:
        listing = client.get('/api/classification/taxonomy/history').json()
        assert len(listing['versions']) == 2
        details = client.get('/api/classification/taxonomy/history/' + first['snapshot_id']).json()
        assert details['impact']['graph_outdated']
        comparison = client.get('/api/classification/taxonomy/history/compare', params={'before': first['snapshot_id'], 'after': current['snapshot_id']}).json()
        assert len(comparison['added']) == 1
        payload = {'expected_current_snapshot_id': current['snapshot_id'], 'expected_graph_version': graph['version']}
        restored = client.post('/api/classification/taxonomy/history/' + first['snapshot_id'] + '/restore', json=payload)
        assert restored.status_code == 200 and restored.json()['impact']['graph_outdated']
        assert client.post('/api/classification/taxonomy/history/' + current['snapshot_id'] + '/restore', json=payload).status_code == 400
        assert client.get('/api/classification/taxonomy/history/not-a-version').status_code == 400
        write_json(workspace[0] / 'jobs/busy.json', {'id': 'busy', 'status': 'running', 'created_at': '2026-01-01'})
        assert client.post('/api/classification/taxonomy/history/' + first['snapshot_id'] + '/restore', json=payload).status_code == 409
    with pytest.raises(ValueError):
        history.get_snapshot('../classification_taxonomy')


def test_generation_writes_snapshots_but_failure_does_not_add_version(workspace, monkeypatch):
    from test_automatic_classification import fake_chat
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(auto, 'chat_json', fake_chat)
    first = auto.build_taxonomy()
    assert first['snapshot_id']
    second = auto.build_taxonomy(rebuild=True)
    assert len(history.history_list()['versions']) == 2
    def fail(*args, **kwargs):
        raise ValueError('模拟失败')
    monkeypatch.setattr(auto, 'chat_json', fail)
    fallback = auto.build_taxonomy(rebuild=True)
    assert fallback['snapshot_id'] == second['snapshot_id']
    assert len(history.history_list()['versions']) == 2
