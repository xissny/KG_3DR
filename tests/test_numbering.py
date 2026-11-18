"""连续编号迁移：临时语料、模拟数据库、原文与审核记录不变、API缓存继续可用。"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from src.common.storage import read_json, write_json, digest, stable_id
from src.papers import numbering, deletion
from src.papers.pipeline import build_paper_list


@pytest.fixture
def gapped(workspace,monkeypatch):
    data,exp=workspace
    originals=read_json(data/'papers.json')
    shifted={p['paper_id']:f'P{i+2:03d}' for i,p in enumerate(originals,1)}
    for folder in ['parsed','candidates','failures']:
        contents={p['paper_id']:read_json(data/folder/f"{p['paper_id']}.json") for p in originals}
        for path in (data/folder).glob('*.json'):path.unlink()
        for old,content in contents.items():
            if content is None:continue
            if isinstance(content,dict):content['paper_id']=shifted[old]
            if folder=='candidates':
                for row in content:row['paper_id']=shifted[old]
            write_json(data/folder/f'{shifted[old]}.json',content)
    papers=[{**p,'paper_id':shifted[p['paper_id']]} for p in originals]
    write_json(data/'papers.json',papers)
    labels=read_json(data/'labels.json')
    write_json(data/'labels.json',{shifted[k]:{**v,'note':'original '+k} for k,v in labels.items()})
    for name in ['graph_snapshot.json','approved_graph.json']:
        graph=read_json(data/name)
        if graph:write_json(data/name,numbering.remap_graph(graph,shifted,{p['paper_id']:p['title'] for p in originals}))
    write_json(data/'paper_registry.json',{'next_number':999,'deleted':[]})
    state={'graph':read_json(data/'graph_snapshot.json')}
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def session(self):return self
        def execute_write(self,function,graph):state['graph']=deepcopy(graph)
    monkeypatch.setattr(numbering.store,'live_graph',lambda:deepcopy(state['graph']))
    monkeypatch.setattr(numbering.store,'driver',Connection)
    return state,papers


def test_existing_gaps_are_migrated_with_all_sources(workspace,gapped):
    data,exp=workspace
    database,papers=gapped
    before_rows=read_json(data/'candidates/P003.json')
    before_ids={r['id'] for p in (data/'candidates').glob('*.json') for r in read_json(p)}
    write_json(exp/'classification.json',{'old':'P003'})
    write_json(exp / 'classification_taxonomy_history/keep.json', {'history': 'preserve'})
    for name in ['automatic_classification', 'classification_taxonomy', 'classification_corrections']:
        write_json(exp / (name + '.json'), {'old': 'P003'})
    result=numbering.renumber_papers()
    assert result['mapping']['P003']=='P001'
    assert result['mapping']['P014']=='P012'
    assert [p['paper_id'] for p in read_json(data/'papers.json')]==[f'P{i:03d}' for i in range(1,13)]
    assert [p['sha256'] for p in read_json(data/'papers.json')]==[p['sha256'] for p in papers]
    after_rows=read_json(data/'candidates/P001.json')
    assert after_rows[0]['id']==before_rows[0]['id']
    assert after_rows[0]['candidate']['quote']==before_rows[0]['candidate']['quote']
    assert after_rows[0]['reviewer']==before_rows[0]['reviewer']
    assert after_rows[0]['paper_id']=='P001'
    assert {r['id'] for p in (data/'candidates').glob('*.json') for r in read_json(p)}==before_ids
    assert read_json(data/'parsed/P001.json')['sha256']==papers[0]['sha256']
    assert not (data/'parsed/P014.json').exists()
    assert read_json(data/'labels.json')['P001']['note']=='original P001'
    assert read_json(data/'paper_registry.json')['next_number']==13
    assert database['graph']['paper_ids']==[f'P{i:03d}' for i in range(1,13)]
    assert len(database['graph']['edges'])==60
    nodes={n['id']:n for n in database['graph']['nodes']}
    assert nodes['P001']['name']==papers[0]['title']
    assert read_json(exp / 'classification_taxonomy_history/keep.json') == {'history': 'preserve'}
    assert not (exp/'classification.json').exists()
    for name in ['automatic_classification', 'classification_taxonomy', 'classification_corrections']:
        assert not (exp / (name + '.json')).exists()
    assert read_json(Path(result['backup'])/'manifest.json')['status']=='complete'
    # 重复执行不再修改数据或产生新编号。
    assert numbering.renumber_papers()['renumbered'] is False


def test_renumbered_pdf_reuses_existing_api_cache(workspace,gapped,monkeypatch):
    from src.extraction import client
    data,_=workspace
    _,papers=gapped
    paper=papers[1]
    monkeypatch.setenv('DEEPSEEK_MODEL','deepseek-flash')
    monkeypatch.setenv('DEEPSEEK_BASE_URL','https://api.deepseek.com')
    context={'paper_id':paper['paper_id'],'paper_title':paper['title'],'page':1,'text':'Cached text only'}
    messages=[{'role':'system','content':'Return JSON'},{'role':'user','content':json.dumps(context,ensure_ascii=False)}]
    payload={'model':'deepseek-flash','messages':messages,'temperature':0,'max_tokens':6000,
             'response_format':{'type':'json_object'},'thinking':{'type':'disabled'}}
    purpose='extract:test:'+paper['sha256']
    key=digest({'base':'https://api.deepseek.com','payload':payload,'purpose':purpose})
    write_json(data/'cache'/f'{key}.json',{'request':payload,'data':{'facts':[]},'raw':{},
               'purpose':purpose,'cache_key':key,'model':'deepseek-flash'})
    rows=read_json(data/'candidates/P004.json');rows[0]['cache_key']=key
    write_json(data/'candidates/P004.json',rows)
    numbering.renumber_papers()
    context['paper_id']='P002'
    messages[1]['content']=json.dumps(context,ensure_ascii=False)
    def forbidden(*args,**kwargs):raise AssertionError('不得调用外部API')
    monkeypatch.setattr(client.httpx,'Client',forbidden)
    result=client.chat_json(messages,purpose)
    assert result['data']=={'facts':[]}
    assert result['renumbered_from_cache_key']==key
    assert read_json(data/'candidates/P002.json')[0]['cache_key']==result['cache_key']


def test_numbering_failure_rolls_back_every_file_and_database(workspace,gapped,monkeypatch):
    data,_=workspace
    state,_=gapped
    originals={p:p.read_bytes() for p in data.rglob('*') if p.is_file()}
    original_graph=deepcopy(state['graph'])
    replace=Path.replace
    def fail(self,target):
        if str(target).endswith('paper_registry.json'):raise OSError('numbering simulated failure')
        return replace(self,target)
    monkeypatch.setattr(Path,'replace',fail)
    with pytest.raises(OSError,match='simulated'):
        numbering.renumber_papers()
    assert all(p.read_bytes()==content for p,content in originals.items())
    assert state['graph']==original_graph
    assert [p['paper_id'] for p in read_json(data/'papers.json')][0]=='P003'


def test_deleted_paper_citation_never_points_to_reused_number():
    graph={'nodes':[{'id':'P001','type':'Paper','name':'Deleted paper'},
                    {'id':'P002','type':'Paper','name':'Retained paper'}],
           'edges':[{'id':'R_old','source':'P002','target':'P001','relation':'CITES',
                     'evidence_ids':['E2'],'paper_ids':['P002']}],
           'evidence':[{'id':'E2','paper_id':'P002'}],'paper_ids':['P001','P002']}
    pruned=deletion.prune_graph(graph,'P001')
    result=numbering.remap_graph(pruned,{'P002':'P001'},{'P002':'Retained paper'})
    citation=result['edges'][0]
    assert citation['source']=='P001'
    assert citation['target']==stable_id('Paper','Deleted paper')
    assert citation['target']!='P001'
    assert next(n for n in result['nodes'] if n['id']=='P001')['name']=='Retained paper'


def test_registration_normalizes_legacy_gaps_before_appending(workspace,gapped):
    papers=build_paper_list(workspace[0]/'pdfs')
    assert len(papers)==12
    assert [p['paper_id'] for p in papers]==[f'P{i:03d}' for i in range(1,13)]


def test_offline_numbering_keeps_imported_graph_unchanged(workspace,gapped,monkeypatch):
    data,_=workspace
    before=(data/'papers.json').read_bytes()
    def offline():raise ConnectionError('offline')
    monkeypatch.setattr(numbering.store,'live_graph',offline)
    with pytest.raises(ValueError,match='启动Neo4j'):
        numbering.renumber_papers()
    assert (data/'papers.json').read_bytes()==before


def test_stale_paper_task_is_rejected_before_api_or_training(workspace):
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as client:
        response=client.post('/api/run',json={'stage':'pipeline','paper_id':'P001','expected_paper_sha256':'old-deleted-content-hash'})
        assert response.status_code==400
        assert '编号已调整' in response.json()['detail']
        assert client.get('/api/jobs').json()==[]


def test_delete_middle_compacts_files_and_preserves_reviews(workspace,monkeypatch):
    data,_=workspace
    before=read_json(data/'papers.json')
    original=deepcopy(read_json(data/'candidates/P007.json'))
    graph=read_json(data/'graph_snapshot.json')
    state={'graph':graph}
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def session(self):return self
        def execute_write(self,function,value):state['graph']=deepcopy(value)
    monkeypatch.setattr(deletion.store,'live_graph',lambda:deepcopy(state['graph']))
    monkeypatch.setattr(deletion.store,'driver',Connection)
    result=deletion.delete_paper('P006')
    assert result['renumbered']['P007']=='P006'
    assert [p['paper_id'] for p in read_json(data/'papers.json')]==[f'P{i:03d}' for i in range(1,12)]
    assert read_json(data/'parsed/P006.json')['sha256']==before[6]['sha256']
    rows=read_json(data/'candidates/P006.json')
    assert rows[0]['id']==original[0]['id'] and rows[0]['reviewer']==original[0]['reviewer']
    assert rows[0]['paper_id']=='P006'
    assert len(state['graph']['edges'])==55


def test_generation_structured_scopes_migrate_and_reference_points_need_review(workspace, gapped):
    data, _ = workspace
    write_json(data/'generation_questions.json', [
        {'id': 'review', 'task_type': 'review',
         'entity_ids': ['P003'], 'paper_ids': ['P003', 'P004'], 'reference_points': ['Original paper P003']},
    ])
    write_json(data/'cache/generation-v2.json', {'purpose': 'graph-generation-v2'})
    numbering.renumber_papers()
    q = read_json(data/'generation_questions.json')[0]
    assert q['entity_ids'] == ['P001']
    assert q['paper_ids'] == ['P001', 'P002']
    assert q['needs_review'] is True
    assert not (data/'cache/generation-v2.json').exists()
