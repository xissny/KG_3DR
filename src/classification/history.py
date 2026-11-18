"""类别体系的不可变快照、差异及恢复；内容版本与操作记录ID分开。"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import re
from uuid import uuid4

from src.common.storage import DATA, EXP, now, read_json, write_json


SNAPSHOT_ID = re.compile(r'^[a-f0-9]{32}$')


def snapshot_path(snapshot_id: str):
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError('类别历史版本ID不合法')
    return EXP / 'classification_taxonomy_history' / f'{snapshot_id}.json'


def archive_snapshot(taxonomy: dict, action: str, previous_id: str | None = None,
                     restored_from: str | None = None) -> dict:
    """以排他创建保存，任何已有历史文件都不会被重写。"""
    snapshot_id = uuid4().hex
    cleaned = {k: deepcopy(v) for k, v in taxonomy.items() if k not in {'snapshot_id', 'last_rebuild_errors'}}
    anchor_ids = {eid for c in cleaned.get('categories', []) for eid in c.get('entity_ids', [])}
    names = ({**get_snapshot(restored_from).get('entity_names', {})} if restored_from else {})
    for node in read_json(DATA / 'graph_snapshot.json', {}).get('nodes', []):
        if node['id'] in anchor_ids and node['id'] not in names:
            names[node['id']] = node['name']
    row = {'entity_names': names, 'snapshot_id': snapshot_id, 'recorded_at': now(), 'action': action,
           'previous_snapshot_id': previous_id, 'restored_from': restored_from, 'taxonomy': cleaned}
    path = snapshot_path(snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 先完成临时文件，再以硬链接原子发布；已有历史文件不可覆盖。
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(row, stream, ensure_ascii=False, indent=2)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return row


def ensure_current_snapshot() -> dict:
    """为升级前的当前体系建立基线；不能还原此前已被覆盖的历史。"""
    current = read_json(EXP / 'classification_taxonomy.json', {})
    if not current:
        return {}
    sid = current.get('snapshot_id')
    if sid and SNAPSHOT_ID.fullmatch(sid):
        archived = read_json(snapshot_path(sid), {})
        if archived.get('taxonomy', {}).get('version') == current.get('version'):
            return current
    baseline = archive_snapshot(current, 'baseline')
    current = {**current, 'snapshot_id': baseline['snapshot_id']}
    write_json(EXP / 'classification_taxonomy.json', current)
    return current


def activate_taxonomy(taxonomy: dict, action: str = 'update', restored_from: str | None = None) -> dict:
    previous = ensure_current_snapshot()
    archived = archive_snapshot(taxonomy, action, previous.get('snapshot_id'), restored_from)
    current = {**deepcopy(taxonomy), 'snapshot_id': archived['snapshot_id']}
    write_json(EXP / 'classification_taxonomy.json', current)
    return current


def get_snapshot(snapshot_id: str) -> dict:
    row = read_json(snapshot_path(snapshot_id))
    if not row:
        raise ValueError('未找到该类别历史版本')
    return row


def history_list() -> dict:
    current = read_json(EXP / 'classification_taxonomy.json', {})
    records = []
    for path in (EXP / 'classification_taxonomy_history').glob('*.json'):
        row = read_json(path)
        if row and row.get('snapshot_id') == path.stem:
            taxonomy = row['taxonomy']
            records.append({k: row.get(k) for k in ['snapshot_id', 'recorded_at', 'action', 'previous_snapshot_id', 'restored_from']} |
                           {'version': taxonomy['version'], 'graph_version': taxonomy.get('graph_version'),
                            'model': taxonomy.get('model'), 'source': taxonomy.get('source'),
                            'generated_at': taxonomy.get('time'), 'category_count': len(taxonomy.get('categories', [])),
                            'is_current': row['snapshot_id'] == current.get('snapshot_id')})
    records.sort(key=lambda r: (r['recorded_at'], r['snapshot_id']), reverse=True)
    return {'current_snapshot_id': current.get('snapshot_id'), 'graph_version': read_json(DATA / 'graph_snapshot.json', {}).get('version'), 'versions': records,
            'legacy_unarchived': bool(current and not current.get('snapshot_id'))}


def compare_taxonomies(before: dict, after: dict) -> dict:
    old = {c['id']: c for c in before.get('categories', [])}
    new = {c['id']: c for c in after.get('categories', [])}
    added = [new[cid] for cid in sorted(new.keys() - old.keys())]
    removed = [old[cid] for cid in sorted(old.keys() - new.keys())]
    fields = ['name', 'dimension', 'definition', 'parent_id', 'entity_ids']
    modified = []
    for cid in sorted(old.keys() & new.keys()):
        changed = [f for f in fields if (set(old[cid].get(f, [])) != set(new[cid].get(f, []))
                                      if f == 'entity_ids' else old[cid].get(f) != new[cid].get(f))]
        if changed:
            modified.append({'before': old[cid], 'after': new[cid], 'fields': changed})
    def overlaps(a, b):
        return a['dimension'] == b['dimension'] and bool(set(a.get('entity_ids', [])) & set(b.get('entity_ids', [])))
    # 只报告基于锚点重叠的候选，不把语义归并误当成已确定事实。
    merges, splits, renames = [], [], []
    for category in new.values():
        sources = [c for c in old.values() if overlaps(c, category)]
        if len(sources) >= 2 and any(c['id'] not in new for c in sources):
            merges.append({'sources': sources, 'target': category})
    for category in old.values():
        targets = [c for c in new.values() if overlaps(category, c)]
        if len(targets) >= 2 and any(c['id'] not in old for c in targets):
            splits.append({'source': category, 'targets': targets})
    merged_ids = {c['id'] for m in merges for c in m['sources']}
    split_ids = {c['id'] for s in splits for c in s['targets']}
    for category in removed:
        targets = [c for c in added if overlaps(category, c)]
        if category['id'] not in merged_ids and len(targets) == 1 and targets[0]['id'] not in split_ids:
            sources = [c for c in removed if overlaps(c, targets[0])]
            if len(sources) == 1:
                renames.append({'before': category, 'after': targets[0]})
    return {'added': added, 'removed': removed, 'modified': modified,
            'possible_merges': merges, 'possible_splits': splits, 'possible_renames': renames,
            'unchanged_count': len(old.keys() & new.keys()) - len(modified),
            'same_content': before.get('version') == after.get('version'),
            'note': '新增、删除和字段变更为精确比较；疑似合并、拆分或改名仅根据关联实体重叠推测。'}


def restore_impact(snapshot: dict) -> dict:
    graph = read_json(DATA / 'graph_snapshot.json', {})
    taxonomy = snapshot['taxonomy']
    rows = read_json(EXP / 'automatic_classification.json', {}).get('papers', {})
    corrections = read_json(EXP / 'classification_corrections.json', {})
    papers = [p for p in read_json(DATA / 'papers.json', []) if p.get('included', True) and p['paper_id'] in graph.get('paper_ids', [])]
    valid, needs, correction_needs = [], [], []
    for paper in papers:
        row = rows.get(paper['paper_id'], {})
        matches = row.get('status') == 'complete' and row.get('taxonomy_version') == taxonomy['version'] and row.get('graph_version') == graph.get('version') and row.get('paper_sha256') == paper.get('sha256')
        (valid if matches else needs).append(paper['paper_id'])
        correction = corrections.get(paper['paper_id'])
        if correction and not (correction.get('taxonomy_version') == taxonomy['version'] and correction.get('graph_version') == graph.get('version') and correction.get('paper_sha256') == paper.get('sha256')):
            correction_needs.append(paper['paper_id'])
    return {'valid_papers': valid, 'needs_classification': needs, 'outdated_corrections': correction_needs,
            'graph_outdated': taxonomy.get('graph_version') != graph.get('version')}


def restore_taxonomy(snapshot_id: str, expected_current_snapshot_id: str | None, expected_graph_version: str) -> dict:
    current = ensure_current_snapshot()
    graph = read_json(DATA / 'graph_snapshot.json', {})
    if current.get('snapshot_id') != expected_current_snapshot_id or graph.get('version') != expected_graph_version:
        raise ValueError('当前类别或图谱已变化，请重新打开历史版本后再恢复')
    selected = get_snapshot(snapshot_id)
    impact = restore_impact(selected)
    restored = activate_taxonomy(selected['taxonomy'], 'restore', restored_from=snapshot_id)
    return {'taxonomy': restored, 'impact': impact, 'message': '历史类别已恢复；未改动图谱、分类结果或个人修订，请按提示重新分类。'}
