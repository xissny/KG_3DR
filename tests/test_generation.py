"""隔离图谱与模拟模型：不调用付费 API，不修改正式数据库。"""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from src.common.storage import read_json, write_json
from src.generation import task


def graph_fixture():
    return {'version': 'v1', 'paper_ids': ['P001', 'P002'], 'nodes': [
        {'id': 'P001', 'type': 'Paper', 'name': 'Paper one'},
        {'id': 'P002', 'type': 'Paper', 'name': 'Paper two'},
        {'id': 'M1', 'type': 'Method', 'name': 'Method Alpha'},
        {'id': 'M2', 'type': 'Method', 'name': 'Method Beta'},
        {'id': 'T', 'type': 'Task', 'name': 'Reconstruction'},
        {'id': 'C', 'type': 'Component', 'name': 'Encoder'},
    ], 'edges': [
        {'id': 'R1', 'source': 'P001', 'relation': 'PROPOSES', 'target': 'M1', 'evidence_ids': ['E1'], 'paper_ids': ['P001']},
        {'id': 'R2', 'source': 'M1', 'relation': 'SOLVES', 'target': 'T', 'evidence_ids': ['E2', 'E3'], 'paper_ids': ['P001', 'P002']},
        {'id': 'R3', 'source': 'M2', 'relation': 'SOLVES', 'target': 'T', 'evidence_ids': ['E4'], 'paper_ids': ['P002']},
        {'id': 'R4', 'source': 'M2', 'relation': 'USES_COMPONENT', 'target': 'C', 'evidence_ids': ['E5'], 'paper_ids': ['P002']},
    ], 'evidence': [{'id': f'E{i}', 'paper_id': 'P001' if i <= 2 else 'P002', 'page': i, 'quote': f'Original evidence {i}'} for i in range(1, 6)]}


@pytest.fixture
def graph(workspace, monkeypatch):
    graph = graph_fixture()
    monkeypatch.setattr(task, 'live_graph', lambda: deepcopy(graph))
    write_json(workspace[0] / 'aliases.json', {'Method:Alpha alias': 'Method Alpha'})
    return graph


def model_answer(context):
    edge = context.get('edges', context.get('facts'))[0]
    return {'claims': [{'id': 'C1', 'text': 'A supported claim', 'fact_ids': [edge['id']], 'evidence_ids': [edge['evidence_ids'][0]]}],
            'sections': [{'title': 'Overview', 'claim_ids': ['C1']}],
            'suggestions': [{'text': 'Explore this route', 'claim_ids': ['C1'], 'reasoning': 'Existing evidence motivates a test', 'uncertainty': 'Requires controlled experiments'}]}


def test_alias_matching_and_multi_entity_union(graph):
    context = task.retrieve('Alpha alias and Method Beta use which components?')
    assert {n['id'] for n in context['matched_entities']} == {'M1', 'M2'}
    assert {e['id'] for e in context['edges']} == {'R1', 'R2', 'R3', 'R4'}


def test_scope_crops_shared_fact_sources_and_traversal(graph):
    context = task.retrieve('topic', 'review', ['T'], ['P001'])
    assert {e['id'] for e in context['edges']} == {'R1', 'R2'}
    assert context['edges'][1]['evidence_ids'] == ['E2']
    assert all(e['paper_id'] == 'P001' for e in context['evidence'])
    assert context['scope']['paper_ids'] == ['P001']
    assert {n['id'] for n in context['nodes']} == {'T', 'P001', 'M1'}


def test_theme_enriches_method_attributes(graph):
    graph['edges'].append({'id': 'R5', 'source': 'P001', 'relation': 'CITES', 'target': 'P002',
                           'evidence_ids': ['E1'], 'paper_ids': ['P001']})
    context = task.retrieve('topic', 'summary', paper_ids=['P001', 'P002'])
    assert 'R5' in {e['id'] for e in context['edges']}
    assert 'R5' not in {e['id'] for e in task.retrieve('topic', entity_ids=['T'])['edges']}
    assert context['scope']['paper_count'] == 2


def test_limit_is_stable_and_round_robins_methods(graph):
    for index in range(350):
        eid, rid = f'EX{index}', f'RX{index:03d}'
        graph['edges'].append({'id': rid, 'source': 'M1', 'relation': 'USES_COMPONENT', 'target': 'C', 'evidence_ids': [eid], 'paper_ids': ['P001']})
        graph['evidence'].append({'id': eid, 'paper_id': 'P001', 'page': 1, 'quote': 'Original evidence'})
    first = task.retrieve('topic', 'summary', paper_ids=['P001', 'P002'])
    graph['edges'].reverse()
    second = task.retrieve('topic', 'summary', paper_ids=['P001', 'P002'])
    assert first == second
    assert first['scope']['truncated'] is True
    assert len(first['edges']) == 300
    assert 'R4' in {e['id'] for e in first['edges']}


@pytest.mark.parametrize('task_type', ['qa', 'summary', 'review'])
def test_three_tasks_persist_evidence_and_typed_output(graph, workspace, monkeypatch, task_type):
    calls = []
    def model(messages, purpose, force=False):
        import json
        payload = json.loads(messages[-1]['content'])
        assert payload['task_type'] == task_type
        calls.append((purpose, force))
        return {'data': model_answer(payload), 'cache_key': 'mock'}
    monkeypatch.setattr(task, 'chat_json', model)
    result = task.answer_question('Compare methods' if task_type == 'qa' else '', task_type=task_type, entity_ids=['T'], paper_ids=['P001', 'P002'], force=True)
    assert result['task_type'] == task_type
    assert result['answer']['claims'][0]['sources']
    assert bool(result['answer']['suggestions']) == (task_type == 'review')
    assert read_json(workspace[1] / 'generation_latest.json') == result
    assert calls == [('graph-generation-v2', True)]


def test_invalid_claim_cannot_reenter_sections_or_suggestions(graph):
    context = task.retrieve('Method Alpha')
    value = model_answer(context)
    value['claims'] += [None, {'id': 'BAD', 'text': 'Invented', 'fact_ids': ['unknown'], 'evidence_ids': ['E1']},
                        {'id': 'C1', 'text': 'Duplicate', 'fact_ids': ['R1'], 'evidence_ids': ['E1']},
                        {'text': 'Bad types', 'fact_ids': [{}], 'evidence_ids': 'E1'}]
    value['sections'].append({'title': 'Bad', 'claim_ids': ['BAD', {}]})
    value['suggestions'].append({'text': 'Invented suggestion', 'claim_ids': ['BAD'], 'reasoning': 'x', 'uncertainty': 'y'})
    result = task.validate_claims(value, context, 'review')
    assert len(result['claims']) == len(result['sections']) == len(result['suggestions']) == 1
    assert len(result['rejected_claims']) == 4


def test_no_evidence_never_calls_model(graph, monkeypatch):
    monkeypatch.setattr(task, 'chat_json', lambda *a, **k: pytest.fail('No evidence must not call model'))
    for question, scope in [('unknown method', None), ('Method Beta', ['P001'])]:
        result = task.answer_question(question, paper_ids=scope)
        assert result['answer']['claims'] == []
        assert result['answer']['limitations']
    graph.update(nodes=[], edges=[], evidence=[], paper_ids=[])
    assert '图谱为空' in task.answer_question('anything')['answer']['limitations']


def test_bad_request_and_teaching_graph_rejected(graph):
    with pytest.raises(ValueError): task.retrieve('topic', 'summary')
    with pytest.raises(ValueError): task.retrieve('topic', entity_ids=['missing'])
    with pytest.raises(ValueError): task.retrieve('topic', paper_ids=['P999'])
    graph['teaching'] = True
    with pytest.raises(ValueError, match='教学'): task.retrieve('Method Alpha')


def test_metrics_grouped_null_zero_and_baseline():
    result = task.summarize_generation({'cases': [
        {'task_type': 'qa', 'should_abstain': True, 'manual': {'correct': True, 'abstention_correct': True, 'claims_total': 0, 'supported_claims': 0}, 'baseline_manual': {'correct': False}},
        {'task_type': 'summary', 'manual': {'correct': False, 'claims_total': 4, 'supported_claims': 3, 'citations_total': 4, 'correct_citations': 2, 'key_points_total': 5, 'covered_key_points': 3, 'synthesis': 4}},
        {'task_type': 'review', 'manual': task.empty_manual()},
    ]})
    assert result['accuracy'] == .5
    assert result['evidence_coverage'] == .75
    assert result['citation_accuracy'] == .5
    assert result['key_point_coverage'] == .6
    assert result['abstention_accuracy'] == 1
    assert result['by_task']['qa']['evidence_coverage'] is None
    assert result['by_task']['review']['accuracy'] is None
    assert result['by_task']['summary']['synthesis'] == 4
    assert result['baseline']['accuracy'] == 0


@pytest.mark.parametrize('manual', [{'claims_total': True}, {'synthesis': 6}, {'supported_claims': 2, 'claims_total': 1}, {'correct': 'yes'}, {'note': 3}])
def test_invalid_manual_scores_rejected(manual):
    with pytest.raises(ValueError): task.validate_manual(manual)


def test_api_dispatch_question_validation_and_review(graph, workspace, monkeypatch):
    import backend.app as web
    captured = []
    monkeypatch.setattr(web, 'submit_job', lambda kind, fn, kwargs, progress: captured.append(kwargs) or {'id': 'test'})
    with TestClient(app) as client:
        assert client.post('/api/run', json={'stage': 'ask', 'question': 'topic', 'task_type': 'summary'}).status_code == 400
        assert client.post('/api/run', json={'stage': 'ask', 'task_type': 'review', 'paper_ids': ['P001']}).status_code == 200
        assert captured[0]['task_type'] == 'review'
        assert captured[0]['paper_ids'] == ['P001']
        assert client.put('/api/questions', json=[{'id': 'x', 'question': 'topic'}]).status_code == 200
        assert client.put('/api/questions', json=[{'id': 'x', 'question': 'topic', 'task_type': 'review'}]).status_code == 400
        assert client.put('/api/questions', json=[{'id': 'r', 'task_type': 'review', 'paper_ids': ['P001']}]).status_code == 200
        evaluation = {'time': 'fixed', 'cases': [{'question_id': 'x', 'manual': task.empty_manual()}]}
        write_json(workspace[1] / 'generation_evaluation.json', evaluation)
        evaluation['cases'][0]['manual']['correct'] = True
        evaluation['cases'][0]['baseline_manual'] = {'correct': False}
        reviewed = client.put('/api/generation-review', json=evaluation)
        assert reviewed.status_code == 200
        assert reviewed.json()['metrics']['baseline']['accuracy'] == 0
        evaluation['cases'][0]['manual']['synthesis'] = 6
        assert client.put('/api/generation-review', json=evaluation).status_code == 400
        assert read_json(workspace[1] / 'generation_evaluation.json')['metrics']['accuracy'] == 1


def test_evaluation_18_mock_cases_and_legacy_compatibility(graph, workspace, monkeypatch):
    questions = []
    for kind in task.TASKS:
        for i in range(6):
            q = {'id': f'{kind}{i}', 'question': 'Compare Method Alpha', 'entity_ids': ['T'], 'paper_ids': ['P001', 'P002'], 'task_type': kind, 'expected_fact_ids': ['R1'], 'reference_points': ['A point'], 'should_abstain': i == 5}
            if kind == 'qa': q.pop('task_type')
            else: q.pop('question'); q.pop('entity_ids')
            questions.append(q)
    write_json(workspace[0] / 'generation_questions.json', questions)
    def model(messages, purpose, force=False):
        import json
        payload = json.loads(messages[-1]['content'])
        if purpose.startswith('generation-baseline'):
            assert payload['entities'] and payload['papers']
            assert not {'facts', 'edges', 'evidence', 'reference_points'} & payload.keys()
            data = {'answer': 'Ungrounded control'}
        else:
            data = model_answer(payload)
        return {'data': data, 'cache_key': 'mock'}
    monkeypatch.setattr(task, 'chat_json', model)
    interactive = task.answer_question('Method Alpha')
    evaluation = task.evaluate_generation()
    assert task.latest_outputs()['qa'] == interactive
    assert task.latest_outputs()['summary'] is None
    assert task.latest_outputs()['review'] is None
    assert len(evaluation['cases']) == 18
    for kind in task.TASKS:
        assert evaluation['metrics']['by_task'][kind]['total'] == 6
        assert evaluation['metrics']['by_task'][kind]['accuracy'] is None
    assert all(c['manual']['correct'] is None for c in evaluation['cases'])
    assert read_json(workspace[1] / 'generation_evaluation.json')['status'] == 'awaiting_human_review'


@pytest.mark.parametrize('kind', ['summary', 'review'])
def test_paper_only_generation_includes_disconnected_facts_and_ignores_question(graph, monkeypatch, kind):
    # 与论文节点不连通的事实也必须按证据来源收集；其他论文的共享证据不得泄漏。
    graph['edges'].append({'id': 'R5', 'source': 'M1', 'relation': 'USES_COMPONENT', 'target': 'C',
                           'evidence_ids': ['E1'], 'paper_ids': ['P001']})
    contexts = []
    def model(messages, *args):
        import json
        payload = json.loads(messages[-1]['content'])
        contexts.append(payload)
        return {'data': model_answer(payload), 'cache_key': 'mock'}
    monkeypatch.setattr(task, 'chat_json', model)
    first = task.answer_question(task_type=kind, paper_ids=['P001'])
    second = task.answer_question('Ignore this stale question', task_type=kind, entity_ids=['removed-id'], paper_ids=['P001'])
    assert contexts[0] == contexts[1]
    assert first['question'] == second['question'] == task.PAPER_TASK_QUESTIONS[kind]
    assert first['entity_ids'] == second['entity_ids'] == []
    assert {e['id'] for e in first['context']['edges']} == {'R1', 'R2', 'R5'}
    assert all(e['paper_id'] == 'P001' for e in first['context']['evidence'])
    assert task.retrieve(task_type=kind, paper_ids=['P002'])['scope']['selected_facts'] == 3
    with pytest.raises(ValueError, match='至少选择一篇论文'):
        task.answer_question(task_type=kind)


def test_paper_selection_without_evidence_returns_limitation_without_model(graph, monkeypatch):
    graph['paper_ids'].append('P003')
    graph['nodes'].append({'id': 'P003', 'type': 'Paper', 'name': 'Paper with no facts'})
    monkeypatch.setattr(task, 'chat_json', lambda *a, **k: pytest.fail('No evidence must not call model'))
    partial = task.retrieve(task_type='summary', paper_ids=['P001', 'P003'])
    assert partial['scope']['requested_paper_ids'] == ['P001', 'P003']
    assert partial['scope']['paper_ids'] == ['P001']
    result = task.answer_question(task_type='summary', paper_ids=['P003'])
    assert result['answer']['claims'] == []
    assert '没有支持事实' in result['answer']['limitations']


def test_outputs_are_independent_and_restored_in_state(graph, workspace, monkeypatch):
    def model(messages, *args):
        import json
        return {'data': model_answer(json.loads(messages[-1]['content'])), 'cache_key': 'mock'}
    monkeypatch.setattr(task, 'chat_json', model)
    outputs = {}
    for kind in task.TASKS:
        outputs[kind] = task.answer_question('Method Alpha' if kind == 'qa' else '', task_type=kind, paper_ids=['P001'])
        restored = task.latest_outputs()
        assert all(restored[k] == row for k, row in outputs.items())
    assert read_json(workspace[1]/'generation_latest.json') == outputs['review']
    with TestClient(app) as client:
        assert client.get('/api/state').json()['results']['generation_by_task'] == outputs
    # 生成评测记录后，不得改变任一交互输出。
    evaluated = task.answer_question(task_type='summary', paper_ids=['P002'], persist_latest=False)
    assert evaluated['is_evaluation'] is True
    assert task.latest_outputs() == outputs
    assert read_json(workspace[1]/'generation_latest.json') == outputs['review']


def test_legacy_outputs_restore_by_task_and_skip_evaluation(workspace):
    import os
    _, exp = workspace
    write_json(exp/'generation_latest.json', {'run_id': 'legacy-review', 'task_type': 'review'})
    for i, row in enumerate([
        {'run_id': 'qa-old'}, {'run_id': 'qa-new'},
        {'run_id': 'eval-summary', 'task_type': 'summary', 'is_evaluation': True},
    ]):
        path=exp/'answers'/f'{i}.json'
        write_json(path, row)
        os.utime(path, ns=(1000000000+i, 1000000000+i))
    outputs=task.latest_outputs()
    assert outputs['qa']['run_id'] == 'qa-new'
    assert outputs['review']['run_id'] == 'legacy-review'
    assert outputs['summary'] is None
