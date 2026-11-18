"""网页接口只组织 I/O；课程算法在 src 下，可从独立脚本直接调用。"""
from __future__ import annotations
from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4
import pymupdf as fitz
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from backend.jobs import LOCK, clear_finished_jobs, list_jobs, recover_jobs, submit_job
from src.common.models import ReviewUpdate
from src.common.identity import canonical_name
from src.common.storage import DATA, EXP, ROOT, digest, read_json, write_json
from src.papers.pipeline import build_paper_list, parse_pdfs, papers_csv, save_papers, allow_reimport
from src.papers.deletion import delete_paper
from src.extraction.pipeline import extract_papers
from src.review.service import all_candidates, grouped_candidates, update_review, validate_facts
from src.review.resolution import ResolutionConflict, ResolutionUpdate, detect_entities, overview as resolution_overview, save_review as save_resolution_review
from src.graph.store import live_graph, import_graph, load_snapshot
from src.classification.task import label_draft, evaluate_classification, classify_paper
from src.classification.automatic import run_automatic_classification, update_taxonomy, classification_overview, save_correction
from src.classification.history import ensure_current_snapshot, history_list, get_snapshot, compare_taxonomies, restore_impact, restore_taxonomy
from src.prediction.task import evaluate_prediction, predict_method, predict_relations, validate_prediction_request
from src.generation.task import answer_question, evaluate_generation, summarize_generation, validate_questions, validate_manual, validate_request, latest_outputs

@asynccontextmanager
async def lifespan(app):
    recover_jobs()
    ensure_current_snapshot()
    yield

app = FastAPI(title='3DR Knowledge Lab', lifespan=lifespan)

@app.middleware('http')
async def refresh_frontend_assets(request, call_next):
    response = await call_next(request)
    if request.url.path in {'/', '/index.html', '/app.js', '/automatic.js', '/taxonomy-history.js', '/entity-resolution.js', '/style.css', '/filters.js', '/snapshot.js', '/prediction.js'}:
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=400, content={'detail': str(exc)})


def idle_only():
    if any(j['status'] in ('queued', 'running') for j in list_jobs()):
        raise HTTPException(409, '后台任务运行中，请等待完成后修改数据')

class StageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage: Literal['papers', 'parse', 'extract', 'pipeline', 'validate', 'import', 'classification', 'classify', 'prediction', 'predict', 'ask', 'generation_eval', 'export', 'materials', 'automatic_classification', 'classification_taxonomy', 'entity_resolution', 'relation_predict']
    paper_id: str | None = None
    expected_paper_sha256: str | None = None
    paper_ids: list[str] | None = None
    method_id: str | None = None
    source_id: str | None = None
    relation_types: list[str] | None = None
    question: str | None = Field(default=None, max_length=4000)
    task_type: Literal['qa', 'summary', 'review'] = 'qa'
    entity_ids: list[str] | None = None
    force: bool = False


def extraction_pipeline(paper_id=None, force=False, progress=None):
    parse_pdfs(paper_id, force, progress)
    return extract_papers(paper_id, force, progress)

@app.get('/api/health')
def health():
    return {'status': 'ok', 'deepseek_configured': bool(os.getenv('DEEPSEEK_API_KEY')),
            'neo4j_browser': f"http://localhost:{os.getenv('NEO4J_HTTP_PORT', '7474')}/browser/"}

@app.get('/api/state')
def state(revision: str | None = None):
    # 文件元数据检查避免空闲轮询反复解析图谱和候选全文。
    paths = [DATA / name for name in ('papers.json', 'graph_snapshot.json', 'paper_registry.json', 'aliases.json', 'labels.json', 'entity_resolution.json')]
    paths += list((DATA / 'candidates').glob('*.json')) + list((DATA / 'jobs').glob('*.json')) + list(EXP.glob('*.json'))
    stamps = []
    for path in sorted(paths):
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            continue
    current_revision = digest(stamps)
    if revision == current_revision:
        return {'unchanged': True, 'revision': current_revision}
    papers = read_json(DATA / 'papers.json', [])
    graph = read_json(DATA / 'graph_snapshot.json', {'nodes': [], 'edges': [], 'version': None})
    candidates = all_candidates()
    auto_paths = [EXP / name for name in ['automatic_classification.json', 'classification_taxonomy.json', 'classification_corrections.json']]
    auto_revision = digest([(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in auto_paths if p.exists()])
    return {'automatic_classification_revision': auto_revision, 'revision': current_revision, 'papers': papers, 'included_count': sum(p.get('included', True) for p in papers),
            'candidate_count': len(candidates), 'pending_evidence_count': sum(f['status']=='pending' for f in candidates), 'unique_candidate_count': len(grouped_candidates(candidates)), 'approved_count': sum(f['status']=='approved' for f in candidates),
            'graph': graph, 'paper_numbering_revision': read_json(DATA / 'paper_registry.json', {}).get('numbering_revision'), 'jobs': list_jobs(), 'aliases': read_json(DATA / 'aliases.json', {}),
            'results': {**{name: read_json(EXP / f'{name}.json') for name in ['classification', 'prediction', 'relation_prediction', 'generation_latest', 'generation_evaluation']}, 'generation_by_task': latest_outputs()}}

@app.get('/api/papers')
def get_papers():
    return read_json(DATA / 'papers.json', [])

@app.get('/api/papers.csv')
def get_papers_csv():
    return Response('\ufeff' + papers_csv(read_json(DATA / 'papers.json', [])), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=papers.csv'})

@app.post('/api/upload')
async def upload(files: list[UploadFile] = File(...)):
    idle_only()
    folder = DATA / 'pdfs'
    folder.mkdir(parents=True, exist_ok=True)
    stored, duplicates, failures = [], [], []
    known = {hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.pdf')}
    for uploaded in files:
        temporary = folder / ('.' + uuid4().hex + '.upload')
        try:
            if not (uploaded.filename or '').lower().endswith('.pdf'):
                raise ValueError('仅支持 PDF')
            total = 0
            with temporary.open('wb') as output:
                while block := await uploaded.read(1024 * 1024):
                    total += len(block)
                    if total > 100 * 1024 * 1024:
                        raise ValueError('单个 PDF 不能超过100MB')
                    output.write(block)
            sha = hashlib.sha256(temporary.read_bytes()).hexdigest()
            if sha in known:
                allow_reimport(sha)
                duplicates.append(uploaded.filename)
                continue
            with fitz.open(temporary) as doc:
                if not len(doc) or doc.needs_pass:
                    raise ValueError('PDF 为空或已加密')
            # 保留可读文件名，去除目录和特殊字符；冲突时添加哈希。
            import re
            filename = re.sub(r'[^\w.()\- ]', '_', Path(uploaded.filename).name)
            target = folder / filename
            if target.exists():
                target = folder / f'{sha[:10]}_{filename}'
            temporary.replace(target)
            known.add(sha)
            allow_reimport(sha)
            stored.append(target.name)
        except Exception as exc:
            failures.append({'file': uploaded.filename, 'error': str(exc)})
        finally:
            temporary.unlink(missing_ok=True)
            await uploaded.close()
    return {'stored': stored, 'duplicates': duplicates, 'failures': failures}

@app.put('/api/papers/{paper_id}')
def edit_paper(paper_id: str, payload: dict):
    idle_only()
    papers = read_json(DATA / 'papers.json', [])
    editable = {'title', 'authors', 'year', 'venue', 'doi_or_arxiv', 'url', 'topic_tags', 'inclusion_reason', 'status', 'included'}
    for paper in papers:
        if paper['paper_id'] == paper_id:
            if payload.get('expected_sha256') and payload['expected_sha256'] != paper['sha256']:
                raise ValueError('论文编号已调整，请刷新页面后再编辑')
            for key, value in payload.items():
                if key in editable:
                    if key == 'included' and not isinstance(value, bool):
                        raise ValueError('included 必须为布尔值')
                    if key != 'included' and not isinstance(value, str):
                        raise ValueError('元数据字段必须为字符串')
                    paper[key] = value
            if not paper['title'].strip():
                raise ValueError('标题不可为空')
            save_papers(papers)
            return paper
    raise HTTPException(404, '未找到论文')


@app.delete('/api/papers/{paper_id}')
def remove_paper(paper_id: str, expected_sha256: str | None = None):
    # 与提交后台任务共用队列锁，避免检查空闲后又启动抽取。
    with LOCK:
        idle_only()
        return delete_paper(paper_id, expected_sha256)

@app.get('/api/candidates')
def candidates(grouped: bool = False, paper_id: str | None = None,
               status: Literal['pending', 'approved', 'rejected'] | None = None):
    # 先筛选底层证据，再分组；同一三元组可同时拥有不同审核状态的来源。
    rows = [row for row in all_candidates()
            if (paper_id is None or row['paper_id'] == paper_id)
            and (status is None or row['status'] == status)]
    return grouped_candidates(rows) if grouped else rows

@app.put('/api/review/{fact_id}')
def review(fact_id: str, payload: ReviewUpdate):
    with LOCK:
        idle_only()
        return update_review(fact_id, payload)

class BulkReview(BaseModel):
    ids: list[str]
    status: Literal['approved', 'rejected', 'pending']
    reviewer: str = Field(min_length=1)
    note: str = ''

@app.post('/api/review-bulk')
def bulk_review(payload: BulkReview):
    with LOCK:
        idle_only()
        result = []
        for fact_id in payload.ids:
            result.append(update_review(fact_id, ReviewUpdate(status=payload.status, reviewer=payload.reviewer, note=payload.note)))
        return {'updated': len(result)}

@app.put('/api/aliases')
def aliases(payload: dict[str, str]):
    with LOCK:
        idle_only()
        allowed = {'Paper', 'Method', 'Component', 'Task', 'Representation', 'Dataset', 'Metric'}
        if any(key.split(':')[0] not in allowed or not value.strip() for key, value in payload.items()):
            raise ValueError('别名格式为 类型:原名 → 标准名，标准名不可为空')
        for key in payload:
            kind, name = key.split(':', 1)
            canonical_name(kind, name, payload)
        write_json(DATA / 'aliases.json', payload)
        return payload

@app.get('/api/entity-resolution')
def get_entity_resolution():
    return resolution_overview()


@app.put('/api/entity-resolution/{suggestion_id}')
def update_entity_resolution(suggestion_id: str, payload: ResolutionUpdate):
    with LOCK:
        idle_only()
        try:
            return save_resolution_review(suggestion_id, payload)
        except ResolutionConflict as exc:
            raise HTTPException(409, str(exc)) from exc


@app.get('/api/graph')
def graph():
    try:
        return live_graph()
    except Exception:
        return JSONResponse(status_code=503, content={'detail': 'Neo4j 不可用，请检查服务；本地快照可在概览或静态 Demo 查看'})

@app.get('/api/evidence/{evidence_id}')
def evidence(evidence_id: str):
    graph = load_snapshot()
    found = next((e for e in graph['evidence'] if e['id'] == evidence_id), None)
    if not found:
        raise HTTPException(404, '证据不存在')
    return found

@app.get('/api/pdf/{paper_id}')
def pdf(paper_id: str):
    paper = next((p for p in read_json(DATA / 'papers.json', []) if p['paper_id'] == paper_id), None)
    if not paper:
        raise HTTPException(404, '论文不存在')
    return FileResponse(paper['pdf_file'], media_type='application/pdf')

@app.get('/api/classification/automatic')
def get_automatic_classification():
    return classification_overview()


@app.get('/api/classification/taxonomy')
def get_classification_taxonomy():
    return read_json(EXP / 'classification_taxonomy.json', {})


@app.get('/api/classification/taxonomy/history')
def list_taxonomy_history():
    return history_list()


@app.get('/api/classification/taxonomy/history/compare')
def compare_taxonomy_history(before: str, after: str):
    return compare_taxonomies(get_snapshot(before)['taxonomy'], get_snapshot(after)['taxonomy'])


@app.get('/api/classification/taxonomy/history/{snapshot_id}')
def inspect_taxonomy_history(snapshot_id: str):
    row = get_snapshot(snapshot_id)
    return {**row, 'impact': restore_impact(row)}


class RestoreTaxonomy(BaseModel):
    expected_current_snapshot_id: str | None = None
    expected_graph_version: str


@app.post('/api/classification/taxonomy/history/{snapshot_id}/restore')
def restore_taxonomy_history(snapshot_id: str, payload: RestoreTaxonomy):
    with LOCK:
        idle_only()
        return restore_taxonomy(snapshot_id, payload.expected_current_snapshot_id, payload.expected_graph_version)


@app.put('/api/classification/automatic/{paper_id}')
def correct_classification(paper_id: str, payload: dict):
    with LOCK:
        idle_only()
        return save_correction(paper_id, payload)


@app.delete('/api/classification/automatic/{paper_id}')
def reset_classification_correction(paper_id: str, graph_version: str, taxonomy_version: str, paper_sha256: str):
    with LOCK:
        idle_only()
        overview = classification_overview()
        paper = next((p for p in overview['papers'] if p['paper_id'] == paper_id), None)
        if not paper or paper_sha256 != paper.get('sha256') or graph_version != overview['graph_version'] or taxonomy_version != overview['taxonomy'].get('version'):
            raise ValueError('论文、图谱或类别已变化，请刷新后操作')
        corrections = read_json(EXP / 'classification_corrections.json', {})
        corrections.pop(paper_id, None)
        write_json(EXP / 'classification_corrections.json', corrections)
        return {'paper_id': paper_id, 'reset': True}


@app.get('/api/labels')
def get_labels():
    graph = load_snapshot()
    draft = label_draft(graph)
    labels = read_json(DATA / 'labels.json', {})
    return {'labels': {p: labels.get(p, row) for p, row in draft.items()},
            'suggestions': draft, 'graph_version': graph['version'],
            'papers': read_json(DATA / 'papers.json', []),
            'tasks': [n for n in graph['nodes'] if n['type'] == 'Task']}


class PaperLabels(BaseModel):
    task_ids: list[str]
    reviewer: str = Field(min_length=1)
    graph_version: str
    note: str = ''


@app.put('/api/labels/{paper_id}')
def confirm_paper_labels(paper_id: str, payload: PaperLabels):
    with LOCK:
        idle_only()
        graph = load_snapshot()
        if payload.graph_version != graph['version']:
            raise HTTPException(409, '图谱已更新，请重新打开标签审核页面')
        if paper_id not in graph['paper_ids']:
            raise ValueError('论文不在当前图谱')
        tasks = {n['id'] for n in graph['nodes'] if n['type'] == 'Task'}
        if not set(payload.task_ids) <= tasks:
            raise ValueError('任务标签不在当前图谱')
        if not payload.reviewer.strip():
            raise ValueError('请填写审核者姓名')
        labels = read_json(DATA / 'labels.json', {})
        labels[paper_id] = {'task_ids': sorted(set(payload.task_ids)), 'verified': True,
                            'reviewer': payload.reviewer.strip(), 'note': payload.note}
        write_json(DATA / 'labels.json', labels)
        return {'paper_id': paper_id, 'label': labels[paper_id]}


@app.put('/api/labels')
def save_labels(payload: dict):
    idle_only()
    graph = load_snapshot()
    task_ids = {n['id'] for n in graph['nodes'] if n['type'] == 'Task'}
    for paper_id, row in payload.items():
        if paper_id not in graph['paper_ids'] or not isinstance(row.get('task_ids'), list):
            raise ValueError('论文或标签结构不正确')
        if not set(row['task_ids']) <= task_ids:
            raise ValueError('任务标签不在当前图谱')
        if row.get('verified') and not row.get('reviewer', '').strip():
            raise ValueError('确认完整标签时必须填写审核者')
    write_json(DATA / 'labels.json', payload)
    return {'saved': len(payload)}

@app.get('/api/questions')
def get_questions():
    return read_json(DATA / 'generation_questions.json', read_json(ROOT / 'examples/generation_questions.json', []))

@app.put('/api/questions')
def save_questions(payload: list[dict]):
    idle_only()
    validate_questions(payload)
    write_json(DATA / 'generation_questions.json', payload)
    return {'saved': len(payload)}

@app.put('/api/generation-review')
def generation_review(payload: dict):
    idle_only()
    current = read_json(EXP / 'generation_evaluation.json')
    if not current or payload.get('time') != current.get('time'):
        raise ValueError('评测版本已变化，请重新读取')
    incoming = {c['question_id']: c.get('manual', {}) for c in payload.get('cases', [])}
    baseline_incoming = {c['question_id']: c.get('baseline_manual', {}) for c in payload.get('cases', [])}
    updates = []
    for case in current['cases']:
        review = incoming.get(case['question_id'], case['manual'])
        baseline_review = baseline_incoming.get(case['question_id'], case.get('baseline_manual', {}))
        validate_manual(review)
        validate_manual(baseline_review)
        updates.append((case, review, baseline_review))
    for case, review, baseline_review in updates:
        case['manual'] = review
        case['baseline_manual'] = baseline_review
    current['status'] = 'reviewed' if all(c.get('manual', {}).get('correct') is not None for c in current['cases']) else 'awaiting_human_review'
    current['metrics'] = summarize_generation(current)
    write_json(EXP / 'generation_evaluation.json', current)
    return current

@app.post('/api/run')
def run(payload: StageRequest):
    if payload.stage == 'relation_predict':
        validate_prediction_request(load_snapshot(), payload.source_id, payload.relation_types)
    if payload.paper_id and payload.expected_paper_sha256:
        current=next((p for p in read_json(DATA/'papers.json',[]) if p['paper_id']==payload.paper_id),None)
        if current is None or current['sha256']!=payload.expected_paper_sha256:
            raise ValueError('论文编号已调整，请刷新页面后重新选择论文')
    if payload.stage == 'ask':
        validate_request(payload.question, payload.task_type, payload.entity_ids, payload.paper_ids)
    from src.graph.export import export_demo
    from src.common.deliverables import build_materials
    operations = {
        'papers': (build_paper_list, {}, False),
        'parse': (parse_pdfs, {'paper_id': payload.paper_id, 'force': payload.force}, True),
        'extract': (extract_papers, {'paper_id': payload.paper_id, 'force': payload.force}, True),
        'pipeline': (extraction_pipeline, {'paper_id': payload.paper_id, 'force': payload.force}, True),
        'entity_resolution': (detect_entities, {'force': payload.force}, True),
        'validate': (validate_facts, {}, False), 'import': (import_graph, {}, False),
        'automatic_classification': (run_automatic_classification, {'paper_ids': payload.paper_ids, 'force': payload.force}, True),
        'classification_taxonomy': (update_taxonomy, {}, True),
        'classification': (evaluate_classification, {}, False),
        'classify': (classify_paper, {'paper_id': payload.paper_id}, False),
        'prediction': (evaluate_prediction, {}, False),
        'relation_predict': (predict_relations, {'source_id': payload.source_id, 'relation_types': payload.relation_types}, True),
        'predict': (predict_method, {'method_id': payload.method_id}, False),
        'ask': (answer_question, {'question': payload.question or '', 'force': payload.force, 'task_type': payload.task_type, 'entity_ids': payload.entity_ids, 'paper_ids': payload.paper_ids}, False),
        'generation_eval': (evaluate_generation, {}, True),
        'export': (export_demo, {}, False), 'materials': (build_materials, {}, False),
    }
    function, arguments, progress = operations[payload.stage]
    return submit_job(payload.stage, function, arguments, progress)

@app.get('/api/jobs')
def jobs():
    return list_jobs()

@app.delete('/api/jobs')
def clear_jobs():
    # 允许其他阶段运行时清理历史，服务层会保留queued/running记录。
    return clear_finished_jobs()

@app.get('/api/example')
def example():
    return read_json(ROOT / 'examples/teaching_snapshot.json', {'nodes': [], 'edges': [], 'evidence': [], 'teaching': True})

@app.get('/api/download/{relative:path}')
def download(relative: str):
    path = (ROOT / 'outputs' / relative).resolve()
    if not path.is_relative_to((ROOT / 'outputs').resolve()) or not path.is_file():
        raise HTTPException(404, '文件不存在')
    return FileResponse(path)

app.mount('/', StaticFiles(directory=ROOT / 'frontend', html=True), name='frontend')
