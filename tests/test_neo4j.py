"""真实数据库集成测试：专属测试命名空间，结束后清理。"""
import uuid
import pytest
from src.common.storage import read_json
from src.graph import store


def test_neo4j_import_is_idempotent_and_keeps_other_projects(workspace,monkeypatch):
    project='kg3dr-test-'+uuid.uuid4().hex[:12]
    monkeypatch.setattr(store,'PROJECT',project)
    try:
        with store.driver() as connection:connection.verify_connectivity()
    except Exception:
        pytest.skip('Neo4j未启动；启动后可验证真实数据库导入')
    try:
        first=store.import_graph();second=store.import_graph()
        assert first==second
        live=store.live_graph()
        assert len(live['edges'])==60
        assert len(live['evidence'])==60
        assert live['version']==first['version']
    finally:
        with store.driver() as connection,connection.session() as session:
            for label in ['KG3DR','KGEvidence','KGMeta']:
                session.run(f'MATCH (n:{label} {{project:$p}}) DETACH DELETE n',p=project).consume()


def test_generation_retrieves_real_neo4j_subgraph(workspace,monkeypatch):
    from src.generation import task
    project='kg3dr-test-'+uuid.uuid4().hex[:12]
    monkeypatch.setattr(store,'PROJECT',project)
    monkeypatch.setattr(task,'PROJECT',project)
    try:
        with store.driver() as connection:connection.verify_connectivity()
    except Exception:
        pytest.skip('Neo4j未启动')
    try:
        store.import_graph()
        context=task.retrieve('Teaching Method 01 uses which components?')
        assert context['edges'] and context['evidence']
        assert all(n['type']!='KGEvidence' for n in context['nodes'])
        fact=context['edges'][0]
        monkeypatch.setattr(task,'chat_json',lambda *a,**k:{'data':{'claims':[{'text':'Synthetic test claim',
            'fact_ids':[fact['id']],'evidence_ids':[fact['evidence_ids'][0]]}],'limitations':'test'},'cache_key':'mock-only'})
        result=task.answer_question('Teaching Method 01 uses which components?')
        assert result['answer']['claims'] and result['context']['graph_version']
    finally:
        with store.driver() as connection,connection.session() as session:
            for label in ['KG3DR','KGEvidence','KGMeta']:
                session.run(f'MATCH (n:{label} {{project:$p}}) DETACH DELETE n',p=project).consume()


def test_paper_deletion_updates_live_graph_and_keeps_shared_fact(workspace,monkeypatch):
    from copy import deepcopy
    from src.papers.deletion import delete_paper
    from src.common.storage import write_json
    project='kg3dr-test-delete-'+uuid.uuid4().hex[:12]
    monkeypatch.setattr(store,'PROJECT',project)
    try:
        with store.driver() as connection:connection.verify_connectivity()
    except Exception:
        pytest.skip('Neo4j未启动')
    try:
        store.import_graph()
        graph=read_json(workspace[0]/'graph_snapshot.json')
        edge=next(e for e in graph['edges'] if e['relation']=='USES_COMPONENT' and e['paper_ids']==['P001'])
        evidence=deepcopy(next(e for e in graph['evidence'] if e['id']==edge['evidence_ids'][0]))
        evidence.update(id='F_shared_from_P002',paper_id='P002')
        graph['evidence'].append(evidence)
        edge['evidence_ids'].append(evidence['id']);edge['paper_ids'].append('P002')
        with store.driver() as connection,connection.session() as session:
            session.execute_write(store._replace_graph,graph)
        write_json(workspace[0]/'graph_snapshot.json',graph)
        removed_hash=read_json(workspace[0]/'papers.json')[0]['sha256']
        result=delete_paper('P001')
        live=store.live_graph()
        assert result['neo4j_updated']
        assert all(e['pdf_sha256']!=removed_hash for e in live['evidence'] if e['id']!='F_shared_from_P002')
        assert len(live['edges'])==56
        shared=next(e for e in live['edges'] if e['id']==edge['id'])
        assert shared['evidence_ids']==['F_shared_from_P002']
        assert shared['paper_ids']==['P001']
        assert live['paper_ids']==[f'P{i:03d}' for i in range(1,12)]
    finally:
        with store.driver() as connection,connection.session() as session:
            for label in ['KG3DR','KGEvidence','KGMeta']:
                session.run(f'MATCH (n:{label} {{project:$p}}) DETACH DELETE n',p=project).consume()
