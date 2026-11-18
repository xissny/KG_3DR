"""阶段 4：人工审核与别名归一。结构正确 ≠ 事实正确。"""
from __future__ import annotations
import os
from src.common.models import Candidate, ReviewUpdate
from src.common.identity import canonical_name, normalized_name, triple_key
from src.common.storage import DATA, digest, now, read_json, stable_id, write_json
from src.extraction.pipeline import check_quote


def all_candidates() -> list[dict]:
    rows = []
    for path in sorted((DATA / 'candidates').glob('*.json')):
        rows.extend(read_json(path, []))
    return rows


def grouped_candidates(rows: list[dict] | None = None, aliases: dict | None = None) -> list[dict]:
    """按标准三元组聚合展示，底层证据ID和审核历史一条不删。

    同一关系可以同时有approved/pending/rejected证据，不能把已审核状态
    自动传播给新证据；每份原文依然独立审核。
    """
    aliases = read_json(DATA / 'aliases.json', {}) if aliases is None else aliases
    groups = {}
    for row in all_candidates() if rows is None else rows:
        candidate = row['candidate']
        key = triple_key(candidate, aliases)
        group = groups.setdefault(key, {
            'id': 'T_' + digest(key)[:20], 'relation': candidate['relation'],
            'subject': {'type': candidate['subject']['type'], 'name': canonical_name(
                candidate['subject']['type'], candidate['subject']['name'], aliases)},
            'object': {'type': candidate['object']['type'], 'name': canonical_name(
                candidate['object']['type'], candidate['object']['name'], aliases)},
            'rows': [], 'status_counts': {'approved': 0, 'pending': 0, 'rejected': 0},
        })
        for field in ['subject', 'object']:
            entity = group[field]
            entity['id'] = stable_id(entity['type'], entity['name'])
        group['rows'].append(row)
        group['status_counts'][row['status']] += 1
    return list(groups.values())


def update_review(fact_id: str, update: ReviewUpdate) -> dict:
    for path in sorted((DATA / 'candidates').glob('*.json')):
        rows = read_json(path, [])
        for row in rows:
            if row['id'] != fact_id:
                continue
            candidate = update.candidate or Candidate.model_validate(row['candidate'])
            parsed = read_json(DATA / 'parsed' / f"{row['paper_id']}.json")
            if not parsed or not check_quote(candidate, parsed):
                raise ValueError('修改后的证据必须能在对应 PDF 页找到')
            row.setdefault('history', []).append({'time': now(), 'previous': {
                'candidate': row['candidate'], 'status': row['status'], 'reviewer': row.get('reviewer'),
                'note': row.get('note')}, 'reviewer': update.reviewer})
            row.update(candidate=candidate.model_dump(), status=update.status,
                       reviewer=update.reviewer, note=update.note, reviewed_at=now())
            write_json(path, rows)
            return row
    raise ValueError('未找到候选事实')


def validate_facts() -> dict:
    """验证证据引用、审核者与实体别名；保存正式图谱快照供导入。"""
    papers = {p['paper_id']: p for p in read_json(DATA / 'papers.json', []) if p.get('included', True)}
    aliases = read_json(DATA / 'aliases.json', {})
    entities, edges, evidence, errors = {}, {}, [], []
    for paper in papers.values():
        entities[paper['paper_id']] = {'id': paper['paper_id'], 'type': 'Paper', 'name': paper['title']}
    for row in all_candidates():
        if row['status'] != 'approved' or row['paper_id'] not in papers:
            continue
        try:
            candidate = Candidate.model_validate(row['candidate'])
            parsed = read_json(DATA / 'parsed' / f"{row['paper_id']}.json")
            if not row.get('reviewer'):
                raise ValueError('缺少审核者')
            if not parsed or parsed['sha256'] != papers[row['paper_id']]['sha256'] or row['pdf_sha256'] != parsed['sha256']:
                raise ValueError('来源文件版本已变化')
            if not check_quote(candidate, parsed):
                raise ValueError('原文证据不存在')
            ids = []
            for entity in [candidate.subject, candidate.object]:
                name = canonical_name(entity.type, entity.name, aliases)
                matching = [p['paper_id'] for p in papers.values() if entity.type == 'Paper' and normalized_name(p['title']) == normalized_name(name)]
                entity_id = matching[0] if matching else stable_id(entity.type, name)
                entities.setdefault(entity_id, {'id': entity_id, 'type': entity.type, 'name': name})
                ids.append(entity_id)
            fact_id = 'R_' + digest([ids[0], candidate.relation, ids[1]])[:20]
            edge = edges.setdefault(fact_id, {'id': fact_id, 'source': ids[0], 'target': ids[1],
                                             'relation': candidate.relation, 'evidence_ids': [], 'paper_ids': []})
            if row['id'] not in edge['evidence_ids']:
                edge['evidence_ids'].append(row['id'])
            if row['paper_id'] not in edge['paper_ids']:
                edge['paper_ids'].append(row['paper_id'])
            evidence.append({'id': row['id'], 'paper_id': row['paper_id'], 'page': candidate.page,
                             'quote': candidate.quote, 'section': row.get('section', ''),
                             'pdf_sha256': row['pdf_sha256'], 'reviewer': row['reviewer'],
                             'reviewed_at': row.get('reviewed_at', ''), 'note': row.get('note', '')})
        except Exception as exc:
            errors.append({'id': row['id'], 'error': str(exc)})
    snapshot = {'nodes': sorted(entities.values(), key=lambda x: x['id']),
                'edges': sorted(edges.values(), key=lambda x: x['id']), 'evidence': evidence,
                'paper_ids': sorted(papers), 'teaching': os.getenv('KG3DR_PROJECT', 'kg3dr-course') == 'kg3dr-teaching'}
    snapshot['version'] = digest(snapshot)
    snapshot['created_at'] = now()
    report = {'errors': errors, 'approved_relations': len(edges), 'evidence_count': len(evidence),
              'paper_count': len(papers), 'version': snapshot['version']}
    write_json(DATA / 'validation.json', report)
    if errors:
        raise ValueError(f'{len(errors)} 条已审核事实未通过校验，详见 data/validation.json')
    write_json(DATA / 'approved_graph.json', snapshot)
    return report
