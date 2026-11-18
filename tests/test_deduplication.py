"""同事实多证据：展示合并，原文与人工判断均不可丢失。"""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from src.common.identity import canonical_name, evidence_key, triple_key
from src.common.storage import read_json, write_json
from src.review.service import grouped_candidates, validate_facts
from src.extraction import pipeline


def test_same_fact_different_quotes_is_one_group_with_independent_reviews(workspace):
    data,_=workspace
    rows=read_json(data/'candidates/P001.json')
    original=deepcopy(rows[0])
    extra=deepcopy(original)
    extra.update(id='F_additional_quote',status='pending',reviewer='',history=[{'note':'preserve me'}])
    extra['candidate']['quote']=extra['candidate']['quote'][:-1]
    rows.append(extra)
    write_json(data/'candidates/P001.json',rows)
    group=next(g for g in grouped_candidates() if any(r['id']==extra['id'] for r in g['rows']))
    assert len(group['rows'])==2
    assert group['status_counts']=={'approved':1,'pending':1,'rejected':0}
    assert group['rows'][1]['history']==extra['history']
    assert len(read_json(data/'candidates/P001.json'))==len(rows)


def test_alias_and_case_normalization_merges_fact_but_not_evidence(workspace):
    data,_=workspace
    row=read_json(data/'candidates/P001.json')[1]
    duplicate=deepcopy(row)
    duplicate['id']='F_alias_test'
    duplicate['candidate']['subject']['name']='  TEACHING   METHOD 01 '
    duplicate['candidate']['object']['name']='global attn'
    write_json(data/'aliases.json',{'Component:global attn':'Global attention'})
    assert triple_key(row['candidate'],read_json(data/'aliases.json'))==triple_key(duplicate['candidate'],read_json(data/'aliases.json'))
    assert len(grouped_candidates([row,duplicate]))==1
    # 更换关系类型不能合并；TRAINED_ON和EVALUATED_ON语义不同。
    changed=deepcopy(row)
    changed['candidate']['relation']='OUTPUTS'
    assert len(grouped_candidates([row,changed]))==2


def test_alias_cycle_rejected_and_width_normalized():
    assert canonical_name('Method',' ＶＧＧＴ ',{})=='VGGT'
    with pytest.raises(ValueError,match='循环'):
        canonical_name('Method','A',{'Method:A':'B','Method:B':'A'})


def test_reextract_whitespace_variant_does_not_add_evidence(workspace,monkeypatch):
    data,_=workspace
    rows=read_json(data/'candidates/P001.json')
    candidate=deepcopy(rows[0]['candidate'])
    candidate['subject']['name']='  '+candidate['subject']['name'].upper()+' '
    candidate['quote']=candidate['quote'].replace(' ','  ')
    monkeypatch.setattr(pipeline,'chat_json',lambda *a,**k:{'data':{'facts':[candidate,candidate]},'cache_key':'mock'})
    result=pipeline.extract_papers('P001')
    assert len(read_json(data/'candidates/P001.json'))==len(rows)
    assert result['papers'][0]['duplicate_evidence_skipped']>=2
    assert read_json(data/'candidates/P001.json')[0]['status']=='approved'


def test_different_page_or_quote_preserved_as_distinct_evidence():
    candidate={'subject':{'type':'Method','name':'A'},'relation':'USES_COMPONENT',
               'object':{'type':'Component','name':'B'},'quote':'A uses B for reconstruction.','page':1}
    changed=deepcopy(candidate);changed['page']=2
    assert evidence_key('sha',candidate,{})!=evidence_key('sha',changed,{})
    changed=deepcopy(candidate);changed['quote']='A adopts B for reconstruction.'
    assert evidence_key('sha',candidate,{})!=evidence_key('sha',changed,{})


def test_approved_duplicates_make_one_edge_with_both_sources(workspace):
    data,_=workspace
    rows=read_json(data/'candidates/P001.json')
    additional=deepcopy(rows[0]);additional['id']='F_second_approved'
    additional['candidate']['subject']['name']=additional['candidate']['subject']['name'].upper()
    rows.append(additional);write_json(data/'candidates/P001.json',rows)
    validate_facts()
    graph=read_json(data/'approved_graph.json')
    assert len(graph['edges'])==60
    assert any(set(e['evidence_ids'])=={rows[0]['id'],'F_second_approved'} for e in graph['edges'])
    assert len(graph['evidence'])==61


def test_grouped_endpoint_is_backward_compatible(workspace):
    with TestClient(app) as client:
        raw=client.get('/api/candidates').json()
        grouped=client.get('/api/candidates?grouped=true').json()
        assert 'candidate' in raw[0]
        assert 'rows' in grouped[0]
        assert sum(len(group['rows']) for group in grouped)==len(raw)
        invalid=client.put('/api/aliases',json={'Method:A':'B','Method:B':'A'})
        assert invalid.status_code==400
