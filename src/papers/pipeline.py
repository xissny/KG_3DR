"""阶段 1/2：PDF 登记与带页码正文切分。不会凭空补全作者或发表信息。"""
from __future__ import annotations
import csv
import hashlib
import io
import re
from pathlib import Path
import pymupdf as fitz
from src.common.storage import DATA, digest, manifest, read_json, write_json

FIELDS = ['paper_id', 'title', 'authors', 'year', 'venue', 'doi_or_arxiv', 'url',
          'pdf_file', 'topic_tags', 'inclusion_reason', 'status']


def save_papers(papers: list[dict]) -> list[dict]:
    ids = [p['paper_id'] for p in papers]
    if len(ids) != len(set(ids)):
        raise ValueError('论文 ID 不可重复')
    write_json(DATA / 'papers.json', papers)
    (DATA / 'papers.csv').write_text(papers_csv(papers), encoding='utf-8-sig')
    return papers


def allow_reimport(sha256: str) -> None:
    """重新上传代表明确重新纳入；普通扫描不会自动找回已删除论文。"""
    registry = read_json(DATA / 'paper_registry.json')
    if registry is not None and any(entry['sha256'] == sha256 for entry in registry.get('deleted', [])):
        registry['reactivated_hashes'] = sorted(set(registry.get('reactivated_hashes', [])) | {sha256})
        write_json(DATA / 'paper_registry.json', registry)


def papers_csv(papers: list[dict]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(papers)
    return stream.getvalue()


def build_paper_list(pdf_dir: Path | None = None) -> list[dict]:
    """元数据自动填写只是草稿：标题和纳入依据仍需在网页校正。"""
    pdf_dir = (pdf_dir or DATA / 'pdfs').resolve()
    papers = read_json(DATA / 'papers.json', [])
    if any(paper['paper_id'] != f'P{index:03d}' for index,paper in enumerate(papers,1)):
        from src.papers.numbering import renumber_papers
        renumber_papers(allow_paper_list_job=True)
        papers = read_json(DATA / 'papers.json', [])
    known_hashes = {p['sha256'] for p in papers}
    registry = read_json(DATA / 'paper_registry.json', {'next_number': 1, 'deleted': []})
    deleted_hashes = {entry['sha256'] for entry in registry.get('deleted', [])}
    deleted_hashes -= set(registry.get('reactivated_hashes', []))
    next_number = len(papers) + 1
    for path in sorted(pdf_dir.glob('*.pdf')):
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha in known_hashes or sha in deleted_hashes:
            continue
        with fitz.open(path) as pdf:
            meta = pdf.metadata or {}
            first_page = pdf[0].get_text() if len(pdf) else ''
            creation = meta.get('creationDate', '')
            year = re.search(r'(?:19|20)\d{2}', creation)
            papers.append({
                'paper_id': f'P{next_number:03d}',
                'title': (meta.get('title') or path.stem).strip(),
                'authors': meta.get('author') or '', 'year': year.group() if year else '',
                'venue': '', 'doi_or_arxiv': '', 'url': '', 'pdf_file': str(path),
                'topic_tags': '', 'inclusion_reason': '', 'status': 'pending',
                'included': True, 'sha256': sha, 'pages': len(pdf),
                'parse_status': 'needs_ocr' if len(first_page.strip()) < 40 else 'ready',
                'metadata_note': 'PDF 元数据待人工核对；创建年份不等于发表年份',
            })
        known_hashes.add(sha)
        next_number += 1
    save_papers(papers)
    registry['next_number'] = next_number
    registry['numbering_policy'] = 'contiguous'
    write_json(DATA / 'paper_registry.json', registry)
    manifest('01_papers', [p['sha256'] for p in papers], {'papers': len(papers)})
    return papers


def parse_pdfs(paper_id: str | None = None, force: bool = False, progress=None) -> dict:
    """保留 PDF 页序号；长页切块采用重叠上下文，证据仍必须在同页出现。"""
    papers = read_json(DATA / 'papers.json', [])
    selected = [p for p in papers if p.get('included', True) and (paper_id is None or p['paper_id'] == paper_id)]
    if not selected:
        raise ValueError('没有可解析论文，请先生成清单并选择纳入论文')
    summary = []
    for index, paper in enumerate(selected):
        output = DATA / 'parsed' / f"{paper['paper_id']}.json"
        previous = read_json(output, {})
        actual_hash = hashlib.sha256(Path(paper['pdf_file']).read_bytes()).hexdigest()
        if actual_hash != paper['sha256']:
            raise ValueError(f"{paper['paper_id']} PDF 已变化，请重新登记")
        if previous.get('sha256') == actual_hash and not force:
            summary.append({'paper_id': paper['paper_id'], 'cached': True})
            continue
        pages, chunks = [], []
        section = 'Unknown'
        with fitz.open(paper['pdf_file']) as pdf:
            for page_number, page in enumerate(pdf, 1):
                text = page.get_text(sort=True)
                for line in text.splitlines():
                    if re.match(r'^\d+(?:\.\d+)*\s+[A-Z][A-Za-z ]{2,70}$', line.strip()):
                        section = line.strip()
                pages.append({'page': page_number, 'text': text, 'section': section})
                for start in range(0, len(text), 6500):
                    fragment = text[start:start + 7500]
                    if fragment.strip():
                        chunks.append({'chunk_id': f'{page_number}_{start}', 'page': page_number,
                                       'section': section, 'text': fragment})
        if sum(len(p['text'].strip()) for p in pages) < 100:
            paper['parse_status'] = 'needs_ocr'
            save_papers(papers)
            raise ValueError(f"{paper['paper_id']} 正文不足，需要 OCR 后重新载入")
        result = {'paper_id': paper['paper_id'], 'sha256': actual_hash,
                  'parser_version': 'pages-v1', 'pages': pages, 'chunks': chunks}
        write_json(output, result)
        summary.append({'paper_id': paper['paper_id'], 'chunks': len(chunks)})
        if progress:
            progress(f"解析 {paper['paper_id']}：{len(chunks)} 块", index + 1, len(selected))
    manifest('02_parse', selected, summary)
    return {'papers': summary}
