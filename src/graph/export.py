"""导出可双击的静态 Demo、CSV/JSON/GraphML；不包含密钥和原始 PDF。"""
from __future__ import annotations
import csv
import io
import json
import shutil
import networkx as nx
from src.common.storage import DATA, EXP, ROOT, now, read_json, write_json


def export_demo() -> dict:
    target = ROOT / 'outputs/demo'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'frontend', target, dirs_exist_ok=True)
    graph = read_json(DATA / 'graph_snapshot.json', {'nodes': [], 'edges': [], 'evidence': [], 'version': None})
    # 不导出服务器绝对 PDF 路径。
    papers = [{k: v for k, v in p.items() if k != 'pdf_file'} for p in read_json(DATA / 'papers.json', [])]
    results = {name: read_json(EXP / f'{name}.json') for name in ['classification', 'prediction', 'relation_prediction', 'generation_latest', 'generation_evaluation']}
    from src.generation.task import latest_outputs
    results['generation_by_task'] = latest_outputs()
    from src.review.service import grouped_candidates
    candidate_groups = grouped_candidates()
    from src.classification.task import label_draft
    suggestions = label_draft(graph)
    saved_labels = read_json(DATA / 'labels.json', {})
    label_review = {'labels': {p: saved_labels.get(p, row) for p, row in suggestions.items()},
                    'suggestions': suggestions, 'graph_version': graph.get('version'),
                    'papers': papers, 'tasks': [n for n in graph['nodes'] if n['type'] == 'Task']}
    from src.classification.automatic import classification_overview
    automatic = classification_overview()
    automatic.pop('deepseek_configured', None)
    from src.classification.history import history_list, get_snapshot
    taxonomy_history = history_list()
    taxonomy_history['snapshots'] = {r['snapshot_id']: get_snapshot(r['snapshot_id']) for r in taxonomy_history['versions']}
    from src.review.resolution import overview as resolution_overview
    bundle = {'entity_resolution': resolution_overview(), 'taxonomy_history': taxonomy_history, 'automatic_classification': automatic, 'label_review': label_review, 'papers': papers, 'graph': graph, 'results': results, 'jobs': [],
              'included_count': sum(p.get('included', True) for p in papers),
              'candidate_groups': candidate_groups,
              'paper_numbering_revision': read_json(DATA / 'paper_registry.json', {}).get('numbering_revision'),
              'candidate_count': sum(len(g['rows']) for g in candidate_groups),
              'approved_count': sum(g['status_counts']['approved'] for g in candidate_groups), 'exported_at': now()}
    teaching = read_json(ROOT / 'examples/teaching_snapshot.json', {})
    # JSON 字符串中转义 < 防止证据中的 HTML/script 结束标签改变页面结构。
    payload = 'window.KG_STATIC=' + json.dumps(bundle, ensure_ascii=False).replace('<', '\\u003c') + ';\n'
    payload += 'window.KG_EXAMPLE=' + json.dumps(teaching, ensure_ascii=False).replace('<', '\\u003c') + ';\n'
    (target / 'snapshot.js').write_text(payload, encoding='utf-8')
    graph_dir = ROOT / 'outputs/graph'
    graph_dir.mkdir(parents=True, exist_ok=True)
    write_json(graph_dir / 'graph.json', graph)
    for name in ['nodes', 'edges', 'evidence']:
        rows = graph[name]
        defaults = {'nodes': ['id','type','name'], 'edges': ['id','source','relation','target','evidence_ids','paper_ids'], 'evidence': ['id','paper_id','page','quote','reviewer']}
        fields = sorted({key for row in rows for key in row}) or defaults[name]
        stream = io.StringIO()
        if fields:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in rows)
        (graph_dir / f'{name}.csv').write_text(stream.getvalue(), encoding='utf-8-sig')
    network = nx.MultiDiGraph()
    for node in graph['nodes']:
        network.add_node(node['id'], name=node['name'], type=node['type'])
    for edge in graph['edges']:
        network.add_edge(edge['source'], edge['target'], key=edge['id'], relation=edge['relation'], evidence_ids=json.dumps(edge['evidence_ids']))
    nx.write_graphml(network, graph_dir / 'graph.graphml')
    return {'demo': str(target / 'index.html'), 'graph_version': graph.get('version'),
            'note': '静态结果只读；正式数据为空时明确显示待载入，教学样例单独打开。'}
