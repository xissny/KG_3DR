import json
import pytest
from pydantic import ValidationError
from src.common.models import Candidate, ReviewUpdate
from src.common.storage import read_json,write_json
from src.classification.features import feature_graph,build_features
from src.classification.task import evaluate_classification,label_draft
from src.prediction.task import hide_group,filtered_rank,evaluate_prediction
from src.generation.task import validate_claims,summarize_generation
from src.review.service import validate_facts,update_review
from src.papers.pipeline import build_paper_list,parse_pdfs


def snapshot(workspace):
    graph=read_json(workspace[0]/'graph_snapshot.json')
    assert graph,'先运行python examples/build_teaching.py创建独立教学样例'
    return graph


def test_schema_rejects_wrong_entity_direction():
    with pytest.raises(ValidationError):
        Candidate.model_validate({'subject':{'type':'Dataset','name':'Dataset A'},'relation':'USES_COMPONENT',
            'object':{'type':'Paper','name':'Paper A'},'quote':'This is a long enough quote.','page':1})


def test_features_ignore_all_task_edges_and_text(workspace):
    graph=snapshot(workspace)
    first=build_features(feature_graph(graph),'P001',2)
    contaminated=json.loads(json.dumps(graph))
    contaminated['nodes'].append({'id':'task_SECRET','type':'Task','name':'Secret correct answer'})
    contaminated['edges'].append({'id':'leak','source':'P001','target':'task_SECRET','relation':'SOLVES'})
    contaminated['evidence']=[{'quote':'The answer is SECRET'}]
    assert build_features(feature_graph(contaminated),'P001',2)==first
    assert 'task_SECRET' not in feature_graph(contaminated)


def test_prediction_hides_entire_method_group(workspace):
    graph=snapshot(workspace)
    training,targets=hide_group(graph,'P001')
    assert targets
    assert not ({e['id'] for e in targets}&{e['id'] for e in training})
    methods={e['target'] for e in graph['edges'] if e['relation']=='PROPOSES' and e['source']=='P001'}
    assert all(not(e['relation']=='USES_COMPONENT' and e['source'] in methods) for e in training)


def test_filtered_rank_uses_average_ties():
    rows=[{'component_id':'a','score':1},{'component_id':'b','score':1},{'component_id':'c','score':0}]
    assert filtered_rank(rows,'a',set(),'score')==1.5
    assert filtered_rank(rows,'a',{'b'},'score')==1
    assert filtered_rank(rows,'missing',set(),'score') is None


def test_missing_complete_labels_reports_gap(workspace):
    data,_=workspace
    write_json(data/'labels.json',{})
    result=evaluate_classification()
    assert result['status']=='insufficient_data'
    assert 'modes' not in result


def test_classification_and_prediction_have_real_cases(workspace):
    graph=snapshot(workspace)
    result=evaluate_classification()
    assert result['status']=='complete'
    assert len(result['modes']['two_hop']['cases'])==12
    assert result['leakage_check']['vectorizer_fit_within_fold']
    prediction=evaluate_prediction()
    assert len(prediction['cases'])==12
    assert prediction['path_model']['coverage']==1


def test_reference_validator_rejects_invented_or_mismatched_ids():
    context={'edges':[{'id':'R1','evidence_ids':['E1']}], 'evidence':[{'id':'E1','paper_id':'P001','page':1}]}
    value={'claims':[{'text':'supported','fact_ids':['R1'],'evidence_ids':['E1']},
                     {'text':'invented','fact_ids':['R2'],'evidence_ids':['E1']}]}
    result=validate_claims(value,context)
    assert len(result['claims'])==1 and len(result['rejected_claims'])==1


def test_unreviewed_generation_does_not_claim_perfect_scores():
    result=summarize_generation({'cases':[{'manual':{'correct':None}}]})
    assert result['accuracy'] is None
    assert result['citation_accuracy'] is None


def test_review_rejects_quote_not_on_page(workspace):
    data,_=workspace
    row=read_json(data/'candidates/P001.json')[0]
    candidate=Candidate.model_validate(row['candidate'])
    candidate.quote='Invented evidence that does not occur in the paper.'
    with pytest.raises(ValueError,match='证据'):
        update_review(row['id'],ReviewUpdate(status='approved',reviewer='tester',candidate=candidate))


def test_pdf_duplicate_and_parse_cache(workspace):
    data,_=workspace
    papers=read_json(data/'papers.json')
    import shutil
    shutil.copy2(papers[0]['pdf_file'],data/'pdfs/duplicate.pdf')
    # 清单源PDF绝对路径在教学目录，当前目录只新增重复文件，仍不可新增记录。
    result=build_paper_list(data/'pdfs')
    assert len(result)==12
    assert parse_pdfs('P001')['papers'][0]['cached']


def test_reviewed_snapshot_has_sources(workspace):
    result=validate_facts()
    assert result['approved_relations']==60
    assert result['errors']==[]
