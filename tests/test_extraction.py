from src.common.storage import read_json
from src.extraction import pipeline


def test_extraction_fixture_is_cached_and_keeps_review(workspace,monkeypatch):
    data,_=workspace
    rows=read_json(data/'candidates/P001.json')
    payload={'facts':[rows[0]['candidate']]}
    monkeypatch.setattr(pipeline,'chat_json',lambda *a,**k:{'data':payload,'cache_key':'fixture'})
    before=len(rows)
    result=pipeline.extract_papers('P001')
    after=read_json(data/'candidates/P001.json')
    assert len(after)==before
    assert after[0]['status']=='approved'


def test_extraction_rejects_invented_quote(workspace,monkeypatch):
    data,_=workspace
    row=read_json(data/'candidates/P001.json')[0]
    row['candidate']['quote']='Invented evidence that does not appear on this page.'
    monkeypatch.setattr(pipeline,'chat_json',lambda *a,**k:{'data':{'facts':[row['candidate']]},'cache_key':'fixture'})
    result=pipeline.extract_papers('P001')
    assert result['papers'][0]['failures']>=1
