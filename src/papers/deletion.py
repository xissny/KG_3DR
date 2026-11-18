"""删除论文及其来源记录：先备份再修改，多来源事实只移除被删论文的证据。

本模块不调用大模型。网页与终端共用；已导入图谱时，Neo4j不可用则拒绝删除，
避免论文消失而数据库仍残留事实。备份用于恢复，不参与正常查询和实验。
"""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4
from src.common.storage import DATA, EXP, ROOT, digest, now, read_json, write_json
from src.papers.pipeline import papers_csv
from src.graph import store
from src.papers.numbering import contiguous_mapping, plan_numbering
from src.papers.transactions import commit_changes

OUTPUTS = Path(os.getenv('KG3DR_OUTPUT_DIR', str(ROOT / 'outputs'))).resolve()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def prune_graph(graph: dict, paper_id: str) -> dict:
    """事实的身份不变；只删除没有其他证据支持的边和不再使用的实体。

    若其他论文仍引用被删论文，保留其作为外部文献的实体，但从语料paper_ids移除。
    删除最后一篇论文时，允许得到空图谱。
    """
    evidence = {e['id']: {k:v for k,v in e.items() if k != 'project'}
                for e in graph.get('evidence', []) if e['paper_id'] != paper_id}
    edges = []
    for original in graph.get('edges', []):
        edge = {k:deepcopy(v) for k,v in original.items() if k != 'project'}
        edge['evidence_ids'] = [eid for eid in edge['evidence_ids'] if eid in evidence]
        if not edge['evidence_ids']:
            continue
        edge['paper_ids'] = sorted({evidence[eid]['paper_id'] for eid in edge['evidence_ids']})
        edges.append(edge)
    paper_ids = sorted(p for p in graph.get('paper_ids', []) if p != paper_id)
    used = {node for edge in edges for node in (edge['source'], edge['target'])} | set(paper_ids)
    used_evidence = {eid for edge in edges for eid in edge['evidence_ids']}
    result = {
        'nodes': [{k:v for k,v in node.items() if k != 'project'} for node in graph.get('nodes', []) if node['id'] in used],
        'edges': edges, 'evidence': [e for eid,e in evidence.items() if eid in used_evidence],
        'paper_ids': paper_ids, 'teaching': graph.get('teaching', False),
    }
    result['version'] = digest(result)
    result['created_at'] = now()
    return result


def graph_mentions(graph: dict, paper_id: str) -> bool:
    return (paper_id in graph.get('paper_ids', []) or
            any(e['paper_id'] == paper_id for e in graph.get('evidence', [])))


@contextmanager
def deletion_lock():
    """防止两个终端同时删除；网页还使用任务队列锁阻止阶段任务插入。"""
    folder = DATA / 'locks'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'paper_delete.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def delete_paper(paper_id: str, expected_sha256: str | None = None) -> dict:
    with deletion_lock():
        return _delete_paper(paper_id, expected_sha256)


def _delete_paper(paper_id: str, expected_sha256: str | None = None) -> dict:
    papers = read_json(DATA / 'papers.json', [])
    target = next((paper for paper in papers if paper['paper_id'] == paper_id), None)
    if not target:
        raise ValueError('未找到论文，可能已经删除')
    if expected_sha256 and target['sha256'] != expected_sha256:
        raise ValueError('论文编号已调整，请刷新页面后再删除；尚未修改任何数据')
    remaining = [paper for paper in papers if paper['paper_id'] != paper_id]
    mapping = contiguous_mapping(remaining)
    touched_ids = {paper_id} | {old for old,new in mapping.items() if old != new}
    for path in (DATA / 'jobs').glob('*.json'):
        if not path.name.endswith('.result.json') and read_json(path, {}).get('status') in ('running','queued'):
            raise ValueError('后台任务运行中，不能删除论文')
    snapshots = {name: read_json(DATA / name) for name in ['graph_snapshot.json','approved_graph.json']}
    live = None
    try:
        live = store.live_graph()
    except Exception as exc:
        if any(graph_mentions(snapshots['graph_snapshot.json'] or {}, pid) for pid in touched_ids):
            raise ValueError('该论文已导入图谱，请先启动Neo4j再删除；尚未修改任何文件') from exc
    graph_changed = live is not None and any(graph_mentions(live, pid) for pid in touched_ids)
    new_live = prune_graph(live, paper_id) if graph_changed else None
    backup = DATA / 'deleted' / f'{paper_id}_{uuid4().hex[:12]}'
    backup.mkdir(parents=True)
    changes: dict[Path, bytes | None] = {}
    changes[DATA/'papers.json'] = json_bytes(remaining)
    changes[DATA/'papers.csv'] = ('\ufeff'+papers_csv(remaining)).encode('utf-8')

    # 删除历史按内容哈希保留；当前论文编号由plan_numbering重新排成连续序列。
    registry = read_json(DATA/'paper_registry.json', {'next_number': 1, 'deleted': []})
    maximum = max([int(p['paper_id'][1:]) for p in papers if re.fullmatch(r'P\d+',p['paper_id'])] or [0])
    registry['next_number'] = max(registry.get('next_number',1), maximum+1)
    registry['reactivated_hashes'] = [sha for sha in registry.get('reactivated_hashes', []) if sha != target['sha256']]
    registry.setdefault('deleted', []).append({'paper_id':paper_id,'sha256':target['sha256'],
                                              'deleted_at':now(),'backup':str(backup)})
    changes[DATA/'paper_registry.json'] = json_bytes(registry)
    for folder in ['parsed','candidates','failures']:
        path = DATA / folder / f'{paper_id}.json'
        if path.exists(): changes[path] = None
    pdf = Path(target['pdf_file']).resolve()
    pdf_managed = pdf.is_relative_to((DATA/'pdfs').resolve())
    same_pdf_needed = any(Path(p['pdf_file']).resolve()==pdf for p in remaining)
    if pdf_managed and pdf.exists() and not same_pdf_needed:
        changes[pdf] = None
    # 外部路径的原始PDF归用户所有，仅删除本项目登记，不触碰外部原文件。
    target_rows = read_json(DATA/'candidates'/f'{paper_id}.json', [])
    target_keys = {r.get('cache_key') for r in target_rows if r.get('cache_key')}
    other_keys = set()
    for path in (DATA/'candidates').glob('*.json'):
        if path.stem != paper_id:
            other_keys.update(row.get('cache_key') for row in read_json(path, []))
    removed_caches = 0
    for path in (DATA/'cache').glob('*.json'):
        cache = read_json(path, {})
        purpose = cache.get('purpose', '')
        belongs = (path.stem in target_keys or
                   (purpose.startswith('extract:') and purpose.endswith(':'+target['sha256'])))
        generated = purpose.startswith(('graph-generation-v', 'generation-baseline-v'))
        if (belongs or generated) and path.stem not in other_keys:
            changes[path] = None
            removed_caches += 1
    labels = read_json(DATA/'labels.json')
    if labels is not None:
        labels.pop(paper_id, None)
        changes[DATA/'labels.json'] = json_bytes(labels)
    audit = read_json(DATA/'quality_audit.json')
    if audit is not None:
        audit['papers'] = [p for p in audit.get('papers', []) if p.get('paper_id') != paper_id]
        changes[DATA/'quality_audit.json'] = json_bytes(audit)
    questions = read_json(DATA/'generation_questions.json')
    if questions is not None:
        remaining_graph = new_live or prune_graph(snapshots['graph_snapshot.json'] or {}, paper_id)
        valid_facts = {e['id'] for e in remaining_graph['edges']}
        valid_entities = {n['id'] for n in remaining_graph['nodes']}
        for question in questions:
            if (set(question.get('expected_fact_ids', [])) - valid_facts
                or set(question.get('entity_ids', [])) - valid_entities
                or paper_id in question.get('paper_ids', []) or paper_id in question.get('entity_ids', [])
                or re.search(r'\b'+re.escape(paper_id)+r'\b', question.get('question',''))):
                question['needs_review'] = True
                question['review_note'] = '论文删除后引用的论文、实体或事实可能失效；请核对内容，不要直接沿用复用后的编号。'
        changes[DATA/'generation_questions.json'] = json_bytes(questions)
    for name, graph in snapshots.items():
        if graph is not None:
            changes[DATA/name] = json_bytes(prune_graph(graph, paper_id))
    if new_live is not None:
        changes[DATA/'graph_snapshot.json'] = json_bytes(new_live)
    # 旧验证报告、实验、作业输出和导出文稿都可能携带该论文，统一移出当前结果。
    for path in [DATA/'validation.json']:
        if path.exists(): changes[path] = None
    derived_folders = [EXP, DATA/'jobs', DATA/'manifests', OUTPUTS/'graph', OUTPUTS/'screenshots']
    for folder in derived_folders:
        if folder.exists():
            for path in folder.rglob('*'):
                if path.is_file() and not path.is_relative_to(EXP / 'classification_taxonomy_history'):
                    changes[path] = None
    for filename in ['project_report.md','project_report.pdf','project_slides.pptx','project_slides.pdf',
                     'speaker_notes.md','kg3dr_project.zip','browser_check.json']:
        path = OUTPUTS/filename
        if path.exists(): changes[path] = None
    # 保留静态页面资源，但替换数据脚本，不能让离线页面继续展示已删论文。
    static_path = OUTPUTS/'demo/snapshot.js'
    if static_path.exists():
        graph = new_live or (prune_graph(snapshots['graph_snapshot.json'],paper_id) if snapshots['graph_snapshot.json'] else
                            {'nodes':[],'edges':[],'evidence':[],'version':None})
        bundle = {'papers':[{k:v for k,v in p.items() if k!='pdf_file'} for p in remaining],
                  'graph':graph,'results':{},'jobs':[], 'included_count':sum(p.get('included',True) for p in remaining),
                  'exported_at':now(),'candidate_count':0,'approved_count':len(graph['edges'])}
        old_script=static_path.read_text(encoding='utf-8')
        marker='window.KG_EXAMPLE='
        teaching=old_script[old_script.index(marker):] if marker in old_script else 'window.KG_EXAMPLE={};\n'
        changes[static_path]=('window.KG_STATIC='+json.dumps(bundle,ensure_ascii=False).replace('<','\\u003c')+';\n'+teaching).encode('utf-8')

    remaining, renumbered = plan_numbering(remaining, changes, OUTPUTS)
    if new_live is not None:
        new_live = json.loads(changes[DATA/'graph_snapshot.json'].decode('utf-8'))
    manifest = {'paper_id':paper_id,'title':target['title'],'deleted_at':now(),
                'pdf_managed':pdf_managed,'neo4j_changed':graph_changed,'renumbered':renumbered}
    database_updated = commit_changes(changes, backup, manifest, live, new_live)
    return {'paper_id':paper_id,'deleted':True,'backup':str(backup),'remaining_papers':len(remaining),
            'removed_evidence_records':len(target_rows),'removed_caches':removed_caches,
            'neo4j_updated':database_updated,'pdf_removed':pdf_managed and not same_pdf_needed,'renumbered':renumbered,
            'note':'关联记录已清理；共享事实保留其他论文证据；剩余论文已连续编号。旧实验与导出成果已备份并失效，请重新评测或导出。',
            'external_pdf_note': '' if pdf_managed else '外部目录PDF保留，仅移除项目登记。'}
