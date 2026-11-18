"""仅在临时语料中测试删除，绝不删除用户论文。"""
from copy import deepcopy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from src.common.storage import read_json, write_json
from src.papers import deletion
from src.papers.pipeline import build_paper_list, allow_reimport


@pytest.fixture
def fake_database(workspace,monkeypatch):
    state={'graph':read_json(workspace[0]/'graph_snapshot.json')}
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def session(self):return self
        def execute_write(self,function,graph):state['graph']=deepcopy(graph)
    monkeypatch.setattr(deletion.store,'live_graph',lambda:deepcopy(state['graph']))
    monkeypatch.setattr(deletion.store,'driver',Connection)
    return state


def make_managed_pdf(data,paper_id):
    papers=read_json(data/'papers.json')
    for paper in papers:
        if paper['paper_id']==paper_id:
            paper['pdf_file']=str(data/'pdfs'/Path(paper['pdf_file']).name)
            pdf=Path(paper['pdf_file'])
    write_json(data/'papers.json',papers)
    assert pdf.exists()
    return pdf


def test_prune_preserves_other_sources_and_shared_entities():
    graph={'nodes':[{'id':key,'type':'Method','name':key} for key in ['M','C','ORPHAN']],
           'edges':[{'id':'R','source':'M','target':'C','relation':'USES_COMPONENT',
                     'evidence_ids':['E1','E2'],'paper_ids':['P001','P002']}],
           'evidence':[{'id':'E1','paper_id':'P001'},{'id':'E2','paper_id':'P002'}],
           'paper_ids':['P001','P002'],'teaching':True}
    result=deletion.prune_graph(graph,'P001')
    assert len(result['edges'])==1
    assert result['edges'][0]['evidence_ids']==['E2']
    assert result['edges'][0]['paper_ids']==['P002']
    assert {n['id'] for n in result['nodes']}=={'M','C'}
    assert graph['edges'][0]['evidence_ids']==['E1','E2']


def test_delete_removes_records_and_archives_results(workspace,fake_database):
    data,exp=workspace
    pdf=make_managed_pdf(data,'P001')
    write_json(exp/'classification.json',{'paper_id':'P001'})
    write_json(exp / 'classification_taxonomy_history/keep.json', {'history': 'preserve'})
    for name in ['automatic_classification', 'classification_taxonomy', 'classification_corrections']:
        write_json(exp / (name + '.json'), {'paper_id': 'P001'})
    outputs=deletion.OUTPUTS
    (outputs/'demo').mkdir(parents=True)
    (outputs/'demo/snapshot.js').write_text('window.KG_STATIC={};\nwindow.KG_EXAMPLE={"teaching":true};')
    (outputs/'project_report.md').write_text('P001 old report')
    write_json(data/'cache/own.json',{'purpose':'extract:v1:'+read_json(data/'papers.json')[0]['sha256']})
    write_json(data/'cache/other.json',{'purpose':'extract:v1:another-sha'})
    original=read_json(data/'papers.json')
    deleted_hash=original[0]['sha256']
    retained_hash=original[1]['sha256']
    result=deletion.delete_paper('P001')
    assert result['remaining_papers']==11
    assert result['neo4j_updated']
    assert not pdf.exists()
    assert read_json(data/'candidates/P001.json')[0]['pdf_sha256']==retained_hash
    assert read_json(data/'parsed/P001.json')['sha256']==retained_hash
    assert not (data/'candidates/P012.json').exists()
    assert [p['paper_id'] for p in read_json(data/'papers.json')]==[f'P{i:03d}' for i in range(1,12)]
    assert not (data/'cache/own.json').exists()
    assert (data/'cache/other.json').exists()
    assert read_json(exp / 'classification_taxonomy_history/keep.json') == {'history': 'preserve'}
    assert not (exp/'classification.json').exists()
    for name in ['automatic_classification', 'classification_taxonomy', 'classification_corrections']:
        assert not (exp / (name + '.json')).exists()
    assert not (outputs/'project_report.md').exists()
    assert len(read_json(data/'labels.json'))==11
    assert len(fake_database['graph']['edges'])==55
    backup=read_json(Path(result['backup'])/'manifest.json')
    assert backup['status']=='complete'
    assert any(Path(record['backup']).read_text()=='P001 old report' for record in backup['files']
               if record['path']==str(outputs/'project_report.md'))
    script=(outputs/'demo/snapshot.js').read_text()
    assert 'window.KG_EXAMPLE=' in script
    assert 'Synthetic Paper 01' not in script
    with pytest.raises(ValueError,match='编号已调整'):
        deletion.delete_paper('P001',expected_sha256=deleted_hash)


def test_deleting_last_paper_creates_empty_graph(workspace,fake_database):
    data,_=workspace
    papers=read_json(data/'papers.json')[:1]
    write_json(data/'papers.json',papers)
    graph=deepcopy(fake_database['graph'])
    # 模拟只有该篇论文的独立图谱。
    graph['evidence']=[e for e in graph['evidence'] if e['paper_id']=='P001']
    eids={e['id'] for e in graph['evidence']}
    graph['edges']=[e for e in graph['edges'] if set(e['evidence_ids'])&eids]
    ids={node for e in graph['edges'] for node in [e['source'],e['target']]}
    graph['nodes']=[n for n in graph['nodes'] if n['id'] in ids]
    graph['paper_ids']=['P001']
    fake_database['graph']=graph
    deletion.delete_paper('P001')
    assert fake_database['graph']['edges']==[]
    assert fake_database['graph']['nodes']==[]
    assert read_json(data/'papers.json')==[]


def test_external_pdf_not_deleted_and_not_rediscovered(workspace,fake_database):
    data,_=workspace
    target=read_json(data/'papers.json')[-1]
    external=Path(target['pdf_file'])
    deletion.delete_paper('P012')
    assert external.exists()
    # 复制到测试扫描目录的同一份PDF也不会无意中重新纳入。
    papers=build_paper_list(data/'pdfs')
    assert len(papers)==11
    allow_reimport(target['sha256'])
    papers=build_paper_list(data/'pdfs')
    assert len(papers)==12
    assert papers[-1]['paper_id']=='P012'


def test_offline_imported_graph_blocks_deletion_without_changes(workspace,monkeypatch):
    data,_=workspace
    before=(data/'papers.json').read_bytes()
    def offline():raise ConnectionError('offline')
    monkeypatch.setattr(deletion.store,'live_graph',offline)
    with pytest.raises(ValueError,match='启动Neo4j'):
        deletion.delete_paper('P001')
    assert (data/'papers.json').read_bytes()==before
    assert not (data/'deleted').exists()


def test_running_job_blocks_delete_api(workspace,fake_database):
    data,_=workspace
    with TestClient(app) as client:
        write_json(data/'jobs/busy.json',{'id':'busy','kind':'pipeline','status':'running','created_at':'2026-01-01'})
        response=client.delete('/api/papers/P001')
        assert response.status_code==409
        assert len(read_json(data/'papers.json'))==12


def test_delete_api_uses_shared_service(workspace,fake_database):
    with TestClient(app) as client:
        deleted_hash=read_json(workspace[0]/'papers.json')[0]['sha256']
        response=client.delete('/api/papers/P001',params={'expected_sha256':deleted_hash})
        assert response.status_code==200
        assert response.json()['remaining_papers']==11
        assert all(row['pdf_sha256']!=deleted_hash for row in client.get('/api/candidates').json())
        stale=client.delete('/api/papers/P001',params={'expected_sha256':deleted_hash})
        assert stale.status_code==400


def test_failed_file_update_restores_files_and_database(workspace,fake_database,monkeypatch):
    data,_=workspace
    before=(data/'papers.json').read_bytes()
    original_graph=deepcopy(fake_database['graph'])
    original_replace=Path.replace
    def failing_replace(self,target):
        if str(target).endswith('paper_registry.json'):
            raise OSError('simulated write failure')
        return original_replace(self,target)
    monkeypatch.setattr(Path,'replace',failing_replace)
    with pytest.raises(OSError,match='simulated'):
        deletion.delete_paper('P001')
    assert (data/'papers.json').read_bytes()==before
    assert fake_database['graph']==original_graph
    assert (data/'candidates/P001.json').exists()


def test_generation_scope_missing_fact_and_v2_cache_invalidated(workspace, fake_database):
    data, _ = workspace
    graph = fake_database['graph']
    lost = next(e for e in graph['edges'] if e['paper_ids'] == ['P012'])
    write_json(data/'generation_questions.json', [
        {'id': 'scope', 'task_type': 'review', 'question': 'Analyze selected task', 'entity_ids': ['P012'], 'paper_ids': ['P012']},
        {'id': 'fact', 'question': 'Analyze evidence', 'expected_fact_ids': [lost['id']]},
    ])
    write_json(data/'cache/generated-v2.json', {'purpose': 'graph-generation-v2'})
    write_json(data/'cache/baseline-v2.json', {'purpose': 'generation-baseline-v2'})
    deletion.delete_paper('P012')  # 删除末篇：不会触发后续编号迁移，仍须标记失效引用。
    assert all(q['needs_review'] for q in read_json(data/'generation_questions.json'))
    assert not (data/'cache/generated-v2.json').exists()
    assert not (data/'cache/baseline-v2.json').exists()
