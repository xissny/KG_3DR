"""阶段 7：显式路径评分与按论文分组遮蔽，不将未观察关系当作负事实。"""
from __future__ import annotations
from collections import Counter
import networkx as nx
import numpy as np
from src.common.storage import EXP, now, write_json
from src.graph.store import load_snapshot


def hide_group(snapshot: dict, paper_id: str) -> tuple[list[dict], list[dict]]:
    methods = {e['target'] for e in snapshot['edges'] if e['relation'] == 'PROPOSES' and e['source'] == paper_id}
    # 同一论文来源和同一方法的组件关系一起隐藏，避免共享来源和重复编码泄漏。
    targets = [e for e in snapshot['edges'] if e['relation'] == 'USES_COMPONENT' and
               (paper_id in e['paper_ids'] or e['source'] in methods)]
    hidden_ids = {e['id'] for e in targets}
    return [e for e in snapshot['edges'] if e['id'] not in hidden_ids], targets


def score_candidates(snapshot: dict, edges: list[dict], method_id: str, top_k: int = 0) -> list[dict]:
    """score(m,c)=二跳路径数+0.5×三跳路径数。只使用允许的关系和规范化实体。

    组件热门度是独立基线，不混入路径分数。无路径候选同分，评测使用平均秩。
    """
    graph = nx.Graph()
    allowed = {'PROPOSES', 'USES_COMPONENT', 'OUTPUTS', 'TRAINED_ON', 'EVALUATED_ON', 'USES_METRIC'}
    for edge in edges:
        if edge['relation'] in allowed:
            graph.add_edge(edge['source'], edge['target'])
    types = {n['id']: n['type'] for n in snapshot['nodes']}
    names = {n['id']: n['name'] for n in snapshot['nodes']}
    frequency = Counter(e['target'] for e in edges if e['relation'] == 'USES_COMPONENT')
    candidates = sorted(c for c in frequency if types.get(c) == 'Component')
    rows = []
    for component in candidates:
        paths = []
        score = 0.0
        if method_id in graph and component in graph:
            # 只枚举2/3跳，数据集规模很小；保存前5条解释路径，但全部参与计分。
            for path in nx.all_simple_paths(graph, method_id, component, cutoff=3):
                length = len(path) - 1
                if length in (2, 3):
                    score += 1.0 if length == 2 else 0.5
                    if len(paths) < 5:
                        paths.append([{'id': node, 'name': names.get(node, node)} for node in path])
        rows.append({'component_id': component, 'name': names.get(component, component),
                     'score': score, 'popularity': frequency[component], 'paths': paths})
    rows.sort(key=lambda row: (-row['score'], row['component_id']))
    return rows[:top_k] if top_k else rows


def filtered_rank(rows: list[dict], target: str, other_known: set[str], field: str) -> float | None:
    filtered = [r for r in rows if r['component_id'] not in other_known or r['component_id'] == target]
    actual = next((r for r in filtered if r['component_id'] == target), None)
    if actual is None:
        return None
    better = sum(r[field] > actual[field] for r in filtered)
    ties = sum(r[field] == actual[field] for r in filtered)
    return 1 + better + (ties - 1) / 2  # 平均秩，不靠实体ID打破平局抬高分数。


def evaluate_prediction() -> dict:
    snapshot = load_snapshot()
    cases = []
    for paper_id in snapshot['paper_ids']:
        training_edges, targets = hide_group(snapshot, paper_id)
        for target in targets:
            rows = score_candidates(snapshot, training_edges, target['source'])
            known = {e['target'] for e in snapshot['edges'] if e['relation'] == 'USES_COMPONENT' and e['source'] == target['source']}
            rank = filtered_rank(rows, target['target'], known, 'score')
            popularity_rank = filtered_rank(rows, target['target'], known, 'popularity')
            cases.append({'held_out_paper': paper_id, 'method_id': target['source'], 'target': target['target'],
                          'rank': rank, 'popularity_rank': popularity_rank, 'covered': rank is not None,
                          'top_candidates': rows[:5], 'hidden_edge_ids': [t['id'] for t in targets]})
    def metrics(key):
        ranks = [c[key] for c in cases if c[key] is not None]
        return {'mrr': float(np.mean([1/r for r in ranks])) if ranks else None,
                'hits_at_1': float(np.mean([r <= 1 for r in ranks])) if ranks else None,
                'hits_at_3': float(np.mean([r <= 3 for r in ranks])) if ranks else None,
                'covered': len(ranks), 'total': len(cases),
                'coverage': len(ranks) / len(cases) if cases else 0,
                'end_to_end_mrr': sum(1/r for r in ranks) / len(cases) if cases else None}
    result = {'status': 'complete' if cases else 'insufficient_data', 'time': now(),
              'graph_version': snapshot['version'], 'path_model': metrics('rank'), 'frequency_baseline': metrics('popularity_rank'),
              'cases': cases, 'tie_policy': '平均秩；Hits 根据平均秩阈值计算',
              'leakage_check': '目标组件边按论文与方法分组移除；不读取文本、任务关系或大模型答案。',
              'limitations': '未观测关系是未知；新组件无法进入训练候选；同分候选多时排名证据较弱。'}
    write_json(EXP / 'prediction.json', result)
    return result


def predict_method(method_id: str) -> dict:
    snapshot = load_snapshot()
    if method_id not in {n['id'] for n in snapshot['nodes'] if n['type'] == 'Method'}:
        raise ValueError('请选择当前图谱中的方法')
    known = {e['target'] for e in snapshot['edges'] if e['relation'] == 'USES_COMPONENT' and e['source'] == method_id}
    rows = [r for r in score_candidates(snapshot, snapshot['edges'], method_id) if r['component_id'] not in known]
    return {'method_id': method_id, 'graph_version': snapshot['version'], 'candidates': rows[:10],
            'status': 'suggestions_only', 'note': '候选是待核验建议，不能作为已知事实。'}


# 日常缺失关系发现与原有组件遮蔽评测独立，避免改变实验口径。
PREDICTABLE_RELATIONS = ('USES_COMPONENT', 'SOLVES', 'OUTPUTS', 'TRAINED_ON',
                         'EVALUATED_ON', 'USES_METRIC')


def validate_prediction_request(snapshot, source_id=None, relation_types=None):
    from src.common.models import RELATION_TYPES
    relations = list(PREDICTABLE_RELATIONS) if relation_types is None else list(dict.fromkeys(relation_types))
    if not relations or any(r not in PREDICTABLE_RELATIONS for r in relations):
        raise ValueError('请选择支持的预测关系类型')
    nodes = {n['id']: n for n in snapshot['nodes']}
    if source_id is not None:
        if source_id not in nodes:
            raise ValueError('请选择当前图谱中的实体')
        if not any(nodes[source_id]['type'] in RELATION_TYPES[r][0] for r in relations):
            raise ValueError('所选实体类型不能作为这些关系的源实体')
    return relations


def discover_relations(snapshot: dict, source_id=None, relation_types=None, progress=None) -> dict:
    """按节点简单路径计分；多关系边保留解释，但不重复增加路径分数。"""
    from collections import defaultdict
    from src.common.models import RELATION_TYPES
    relations = validate_prediction_request(snapshot, source_id, relation_types)
    nodes = {n['id']: n for n in snapshot['nodes']}
    graph = nx.Graph()
    graph.add_nodes_from(sorted(nodes))
    edge_groups = defaultdict(list)
    targets = defaultdict(set)
    known = set()
    allowed = set(PREDICTABLE_RELATIONS) | {'PROPOSES'}
    for edge in sorted(snapshot['edges'], key=lambda e: e['id']):
        source, target, relation = edge['source'], edge['target'], edge['relation']
        if source not in nodes or target not in nodes:
            continue
        known.add((source, relation, target))
        if relation in relations and nodes[target]['type'] in RELATION_TYPES[relation][1]:
            targets[relation].add(target)
        if relation in allowed and source != target:
            graph.add_edge(source, target)
            edge_groups[tuple(sorted((source, target)))].append(edge)
    sources = sorted(n for n in nodes if (source_id is None or n == source_id) and
                     any(nodes[n]['type'] in RELATION_TYPES[r][0] for r in relations))
    candidates = []
    positive_count = 0
    for index, source in enumerate(sources):
        # 一次枚举该源的所有2/3跳路径，而非为每个目标重复遍历。
        scores = defaultdict(float)
        counts = Counter()
        explanations = defaultdict(list)
        def visit(path):
            depth = len(path) - 1
            if depth >= 2:
                target = path[-1]
                scores[target] += 1 if depth == 2 else .5
                counts[target] += 1
                if len(explanations[target]) < 5:
                    steps = [edge_groups[tuple(sorted((a, b)))] for a, b in zip(path, path[1:])]
                    edges = [e for group in steps for e in group]
                    explanations[target].append({
                        'node_ids': list(path), 'edge_ids': [e['id'] for e in edges],
                        'steps': [[e['id'] for e in group] for group in steps],
                        'evidence_ids': sorted({eid for e in edges for eid in e.get('evidence_ids', [])})})
            if depth == 3:
                return
            for neighbor in sorted(graph[path[-1]]):
                if neighbor not in path:
                    visit(path + [neighbor])
        visit([source])
        for relation in relations:
            if nodes[source]['type'] not in RELATION_TYPES[relation][0]:
                continue
            rows = []
            for target in sorted(targets[relation]):
                if target == source or (source, relation, target) in known or scores[target] <= 0:
                    continue
                rows.append({'source_id': source, 'relation': relation, 'target_id': target,
                             'score': scores[target], 'path_count': counts[target],
                             'paths': explanations[target]})
            rows.sort(key=lambda row: (-row['score'], row['target_id']))
            positive_count += len(rows)
            candidates.extend(rows[:10])
        if progress:
            progress(f'已扫描 {index + 1}/{len(sources)} 个实体', index + 1, len(sources))
    candidates.sort(key=lambda row: (-row['score'], row['source_id'], row['relation'], row['target_id']))
    # 保留本次解释用到的版本化上下文，旧结果不与新图谱证据混合。
    edge_ids = {eid for c in candidates for p in c['paths'] for eid in p['edge_ids']}
    node_ids = {nid for c in candidates for p in c['paths'] for nid in p['node_ids']}
    evidence_ids = {eid for c in candidates for p in c['paths'] for eid in p['evidence_ids']}
    return {'status': 'suggestions_only', 'time': now(), 'graph_version': snapshot.get('version'),
            'scope': {'source_id': source_id, 'relation_types': relations},
            'statistics': {'scanned_sources': len(sources), 'candidate_count': len(candidates),
                           'positive_count': positive_count},
            'candidates': candidates,
            'context': {'nodes': [nodes[n] for n in sorted(node_ids)],
                        'edges': [e for e in snapshot['edges'] if e['id'] in edge_ids],
                        'evidence': [e for e in snapshot.get('evidence', []) if e['id'] in evidence_ids]},
            'note': '路径分数不是概率。原文证据支持路径中的已有关系，预测关系仍待核验。'}


def predict_relations(source_id=None, relation_types=None, progress=None) -> dict:
    result = discover_relations(load_snapshot(), source_id, relation_types, progress)
    write_json(EXP / 'relation_prediction.json', result)
    return result
