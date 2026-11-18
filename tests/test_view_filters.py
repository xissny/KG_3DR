"""筛选必须发生在证据层；测试仅使用临时目录和虚构样例。"""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from src.common.storage import read_json, write_json


def test_candidate_endpoint_filters_before_grouping(workspace):
    data, _ = workspace
    rows = read_json(data / 'candidates/P001.json')
    pending = deepcopy(rows[0])
    pending.update(id='F_pending_view',status='pending',reviewer='')
    rejected = deepcopy(rows[0])
    rejected.update(id='F_rejected_view',status='rejected')
    rows.extend([pending, rejected])
    write_json(data / 'candidates/P001.json', rows)
    with TestClient(app) as client:
        response = client.get('/api/candidates', params={'grouped':True,'paper_id':'P001','status':'pending'})
        assert response.status_code == 200
        groups = response.json()
        assert len(groups) == 1
        assert [r['id'] for r in groups[0]['rows']] == ['F_pending_view']
        assert groups[0]['status_counts'] == {'approved':0,'pending':1,'rejected':0}
        assert client.get('/api/candidates',params={'paper_id':'P002','status':'pending'}).json() == []
        assert client.get('/api/candidates',params={'paper_id':'missing'}).json() == []
        assert client.get('/api/candidates',params={'status':'unknown'}).status_code == 422
    # 查询筛选不改变审核历史或状态。
    assert read_json(data / 'candidates/P001.json') == rows


def test_browser_shared_filter_functions():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    if not node:
        import playwright
        candidate = Path(playwright.__file__).parent / 'driver/node'
        if candidate.is_file(): node = str(candidate)
    if not node: pytest.skip('Node未安装，可使用Playwright自带Node运行JS筛选测试')
    result = subprocess.run([node,str(root / 'tests/view_filters.test.cjs')],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout + result.stderr
