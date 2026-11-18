"""标签审核使用隔离教学数据，验证逐篇保存与空闲轮询。"""
from fastapi.testclient import TestClient
from backend.app import app
from src.common.storage import read_json, write_json


def test_visual_labels_confirm_one_paper_without_overwriting_others(workspace):
    data, _ = workspace
    with TestClient(app) as client:
        value = client.get('/api/labels').json()
        assert value['suggestions'] and value['tasks'] and value['papers']
        ids = list(value['labels'])
        untouched = value['labels'][ids[1]]
        task = value['tasks'][0]['id']
        response = client.put('/api/labels/' + ids[0], json={
            'task_ids': [task, task], 'reviewer': ' 测试审核者 ',
            'note': '人工确认', 'graph_version': value['graph_version']})
        assert response.status_code == 200
        saved = read_json(data / 'labels.json')
        assert saved[ids[0]] == {'task_ids': [task], 'reviewer': '测试审核者', 'verified': True, 'note': '人工确认'}
        assert saved[ids[1]] == untouched
        again = client.get('/api/labels').json()
        assert again['labels'][ids[0]] == saved[ids[0]]
        assert again['suggestions'] == value['suggestions']


def test_label_confirmation_rejects_invalid_or_stale_input(workspace):
    with TestClient(app) as client:
        value = client.get('/api/labels').json()
        paper = next(iter(value['labels']))
        valid = {'task_ids': [], 'reviewer': '审核者', 'graph_version': value['graph_version']}
        for changes, status in [({'reviewer': '  '}, 400), ({'task_ids': ['unknown']}, 400), ({'graph_version': 'old'}, 409)]:
            assert client.put('/api/labels/' + paper, json=valid | changes).status_code == status
        assert client.put('/api/labels/missing', json=valid).status_code == 400
        assert client.put('/api/labels/' + paper, json=valid).json()['label']['task_ids'] == []
        write_json(workspace[0] / 'jobs/busy.json', {'id': 'busy', 'status': 'running', 'created_at': '2026-01-01'})
        assert client.put('/api/labels/' + paper, json=valid).status_code == 409


def test_state_revision_skips_unchanged_data_and_detects_edits(workspace, monkeypatch):
    import backend.app as module
    with TestClient(app) as client:
        first = client.get('/api/state').json()
        def expensive_read():
            raise AssertionError('空闲轮询不应重新读取候选事实')
        with monkeypatch.context() as scoped:
            scoped.setattr(module, 'all_candidates', expensive_read)
            assert client.get('/api/state', params={'revision': first['revision']}).json() == {'unchanged': True, 'revision': first['revision']}
        write_json(workspace[0] / 'aliases.json', {'Component:test': 'new'})
        changed = client.get('/api/state', params={'revision': first['revision']}).json()
        assert changed['revision'] != first['revision'] and changed['aliases']
