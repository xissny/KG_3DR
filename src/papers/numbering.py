"""连续论文编号：P001...Pn；内容哈希和证据ID不变，展示编号及引用一起迁移。

先在内存准备全部变更，再交给transactions备份和提交，不能逐文件直接rename：
删除P001后，旧P002/P003目标文件名均可能已存在，直接rename会覆盖原数据。
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import re
from uuid import uuid4
from src.common.storage import DATA, EXP, digest, now, read_json, stable_id
from src.graph import store
from src.papers.transactions import commit_changes


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def contiguous_mapping(papers: list[dict]) -> dict[str, str]:
    """维持清单原有顺序；不按标题或文件名重新排序。"""
    ids=[paper['paper_id'] for paper in papers]
    if len(ids)!=len(set(ids)):
        raise ValueError('论文编号重复，不能自动迁移，请先修复清单')
    return {paper['paper_id']: f'P{index:03d}' for index, paper in enumerate(papers, 1)}


def remap_graph(graph: dict, mapping: dict[str, str], titles: dict[str, str]) -> dict:
    """重写实体/证据来源与关系ID；被删但仍被引用的论文变为外部文献实体。"""
    nodes, node_ids = {}, {}
    for original in graph.get('nodes', []):
        node = {k: deepcopy(v) for k, v in original.items() if k != 'project'}
        old_id = node['id']
        if node.get('type') == 'Paper':
            if old_id in mapping:
                node['id'] = mapping[old_id]
                node['name'] = titles[old_id]
            elif node.get('name') in mapping:
                node['id'] = mapping[node['name']]
                node['name'] = titles[node['name']]
            elif re.fullmatch(r'P\d+', old_id):
                # 原论文已删，编号将被复用；外部引用不能误连到新的P001。
                node['id'] = stable_id('Paper', node['name'])
        node_ids[old_id] = node['id']
        nodes[node['id']] = node
    evidence = []
    for original in graph.get('evidence', []):
        row = {k: deepcopy(v) for k, v in original.items() if k != 'project'}
        row['paper_id'] = mapping.get(row['paper_id'], row['paper_id'])
        evidence.append(row)
    evidence_by_id = {e['id']: e for e in evidence}
    edges = {}
    for original in graph.get('edges', []):
        source = node_ids.get(original['source'], original['source'])
        target = node_ids.get(original['target'], original['target'])
        relation = original['relation']
        edge_id = 'R_' + digest([source, relation, target])[:20]
        edge = edges.setdefault(edge_id, {'id':edge_id,'source':source,'target':target,
                                          'relation':relation,'evidence_ids':[],'paper_ids':[]})
        edge['evidence_ids'] = sorted(set(edge['evidence_ids']) | set(original.get('evidence_ids', [])))
        edge['paper_ids'] = sorted(set(edge['paper_ids']) | {
            evidence_by_id[eid]['paper_id'] for eid in original.get('evidence_ids', []) if eid in evidence_by_id})
    result = {'nodes': sorted(nodes.values(), key=lambda n:n['id']),
              'edges': sorted(edges.values(), key=lambda e:e['id']), 'evidence': evidence,
              'paper_ids': sorted(mapping.get(pid,pid) for pid in graph.get('paper_ids', [])),
              'teaching': graph.get('teaching', False)}
    result['version'] = digest(result)
    result['created_at'] = now()
    return result


def map_paper_entities(candidate: dict, titles: dict[str, str]) -> dict:
    result = deepcopy(candidate)
    for field in ['subject','object']:
        entity = result.get(field, {})
        if entity.get('type') == 'Paper' and entity.get('name') in titles:
            entity['name'] = titles[entity['name']]
    return result


def invalidate_derived(changes: dict, outputs: Path) -> None:
    """旧实验/生成引用/导出材料由事务移入备份，避免旧编号与新论文混淆。"""
    for folder in [EXP, DATA/'jobs', DATA/'manifests', outputs/'graph', outputs/'screenshots']:
        for path in folder.rglob('*') if folder.exists() else []:
            if path.is_file():
                if path.is_relative_to(EXP / 'classification_taxonomy_history'):
                    continue
                if folder == DATA/'jobs' and not path.name.endswith('.result.json'):
                    job = read_json(path, {})
                    if job.get('kind') == 'papers' and job.get('status') in ('running','queued'):
                        continue
                changes[path] = None
    for filename in ['validation.json']:
        if (DATA/filename).exists(): changes[DATA/filename] = None
    for filename in ['project_report.md','project_report.pdf','project_slides.pptx','project_slides.pdf',
                     'speaker_notes.md','kg3dr_project.zip','browser_check.json','paper_filters_check.json']:
        if (outputs/filename).exists(): changes[outputs/filename] = None


def plan_numbering(papers: list[dict], changes: dict[Path, bytes | None], outputs: Path) -> tuple[list[dict], dict]:
    """对待提交的变更叠加编号迁移；只准备字节，不修改任何文件。"""
    from src.papers.pipeline import papers_csv
    from src.review.service import grouped_candidates
    mapping = contiguous_mapping(papers)
    changed = {old:new for old,new in mapping.items() if old != new}
    titles = {p['paper_id']:p['title'] for p in papers}
    def get(path, default=None):
        if path in changes:
            return default if changes[path] is None else json.loads(changes[path].decode('utf-8-sig'))
        return read_json(path, default)
    numbered = [{**paper,'paper_id':mapping[paper['paper_id']]} for paper in papers]
    registry_path = DATA/'paper_registry.json'
    registry = get(registry_path, {'deleted':[]})
    registry.update(next_number=len(numbered)+1, numbering_policy='contiguous')
    if changed:
        revision = uuid4().hex
        registry['numbering_revision'] = revision
        registry.setdefault('numbering_history', []).append({'revision':revision,'time':now(),'mapping':changed})
    changes[registry_path] = json_bytes(registry)
    changes[DATA/'papers.json'] = json_bytes(numbered)
    changes[DATA/'papers.csv'] = ('\ufeff'+papers_csv(numbered)).encode('utf-8')
    if not changed:
        return numbered, changed

    invalidate_derived(changes, outputs)
    aliases = get(DATA/'aliases.json', {})
    new_aliases = {}
    for key, value in aliases.items():
        kind, _, name = key.partition(':')
        if kind == 'Paper':
            name, value = titles.get(name,name), titles.get(value,value)
        new_key = kind+':'+name
        if new_key in new_aliases and new_aliases[new_key] != value:
            raise ValueError('编号迁移导致论文别名冲突，请先检查别名表')
        new_aliases[new_key] = value
    if aliases != new_aliases: changes[DATA/'aliases.json'] = json_bytes(new_aliases)

    # 重命名缓存键，使仅编号变化时仍能命中原API结果，不调用付费服务。
    hashes = {p['sha256']:p['paper_id'] for p in papers}
    cache_moves, cache_keys = [], {}
    for path in (DATA/'cache').glob('*.json'):
        cache = get(path)
        if not cache: continue
        purpose = cache.get('purpose','')
        if purpose.startswith(('graph-generation-v', 'generation-baseline-v')):
            changes[path] = None
            continue
        if not purpose.startswith('extract:'): continue
        old_id = hashes.get(purpose.rsplit(':',1)[-1])
        if old_id not in mapping: continue
        request = deepcopy(cache.get('request'))
        if not isinstance(request,dict): continue
        modified = False
        for message in request.get('messages', []):
            if message.get('role') != 'user': continue
            try: context = json.loads(message.get('content',''))
            except (ValueError, TypeError): continue
            if isinstance(context,dict) and 'paper_id' in context and 'text' in context:
                context['paper_id'] = mapping[old_id]
                message['content'] = json.dumps(context, ensure_ascii=False)
                modified = True
        if not modified: continue
        base = cache.get('base_url') or os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/')
        key = digest({'base':base,'payload':request,'purpose':purpose})
        migrated = deepcopy(cache)
        migrated.update(request=request,cache_key=key,base_url=base,renumbered_from_cache_key=path.stem)
        migrated.setdefault('original_request', cache.get('request'))
        if isinstance(migrated.get('data'),dict) and isinstance(migrated['data'].get('facts'),list):
            migrated['data']['facts'] = [map_paper_entities(f,titles) for f in migrated['data']['facts']]
        cache_keys[path.stem] = key
        cache_moves.append((path,DATA/'cache'/f'{key}.json',migrated))
    for old,_,_ in cache_moves: changes[old] = None
    for _,new,cache in cache_moves: changes[new] = json_bytes(cache)

    # 先全部读入、标记旧路径删除，再安排目标路径写入，避免P002→P001覆盖。
    moves, remaining_rows = [], []
    for folder in ['parsed','candidates','failures']:
        for paper in papers:
            old_id = paper['paper_id']
            old = DATA/folder/f'{old_id}.json'
            content = get(old)
            if content is None: continue
            if folder == 'parsed':
                content['paper_id'] = mapping[old_id]
            elif folder == 'candidates':
                for row in content:
                    row['paper_id'] = mapping.get(row['paper_id'],row['paper_id'])
                    row['candidate'] = map_paper_entities(row['candidate'], titles)
                    if row.get('cache_key') in cache_keys: row['cache_key'] = cache_keys[row['cache_key']]
                remaining_rows.extend(content)
            moves.append((old,DATA/folder/f'{mapping[old_id]}.json',content))
    for old,_,_ in moves: changes[old] = None
    for _,new,content in moves: changes[new] = json_bytes(content)

    labels = get(DATA/'labels.json')
    if labels is not None:
        changes[DATA/'labels.json'] = json_bytes({mapping.get(key,key):row for key,row in labels.items()})
    audit = get(DATA/'quality_audit.json')
    if audit is not None:
        for row in audit.get('papers', []):
            row['paper_id'] = mapping.get(row.get('paper_id'),row.get('paper_id'))
        changes[DATA/'quality_audit.json'] = json_bytes(audit)
    for filename in ['graph_snapshot.json','approved_graph.json']:
        graph = get(DATA/filename)
        if graph is not None: changes[DATA/filename] = json_bytes(remap_graph(graph,mapping,titles))
    # 题目可包含旧关系ID/编号，保留一份历史副本，当前题目只迁移精确结构化引用。
    questions = get(DATA/'generation_questions.json')
    if questions is not None:
        old_graph = read_json(DATA/'graph_snapshot.json', {})
        new_graph = get(DATA/'graph_snapshot.json', {})
        new_edges = {(e['source'],e['relation'],e['target']):e['id'] for e in new_graph.get('edges', [])}
        edge_ids = {e['id']:new_edges.get((mapping.get(e['source'],e['source']),e['relation'],mapping.get(e['target'],e['target'])),e['id'])
                    for e in old_graph.get('edges', [])}
        valid_entities = {n['id'] for n in new_graph.get('nodes', [])}
        for question in questions:
            for field in ('paper_ids', 'entity_ids'):
                if field in question:
                    question[field] = [mapping.get(value, value) for value in question[field]]
            if set(question.get('entity_ids', [])) - valid_entities:
                question['needs_review'] = True
            if question.get('reference_points'):
                question['needs_review'] = True
            question['expected_fact_ids'] = [edge_ids.get(fid,fid) for fid in question.get('expected_fact_ids', [])]
            if any(fid not in set(new_edges.values()) for fid in question['expected_fact_ids']):
                question['needs_review'] = True
            if isinstance(question.get('question'), str):
                question['question'] = re.sub(r'\bP\d+\b',lambda match:mapping.get(match.group(),match.group()),question['question'])
        changes[DATA/'generation_questions.json'] = json_bytes(questions)

    static = outputs/'demo/snapshot.js'
    if static.exists():
        old_script = static.read_text(encoding='utf-8')
        marker = 'window.KG_EXAMPLE='
        teaching = old_script[old_script.index(marker):] if marker in old_script else 'window.KG_EXAMPLE={};\n'
        graph = get(DATA/'graph_snapshot.json', {'nodes':[],'edges':[],'evidence':[],'version':None})
        groups = grouped_candidates(remaining_rows, aliases=new_aliases)
        bundle = {'papers':[{k:v for k,v in p.items() if k!='pdf_file'} for p in numbered],
                  'graph':graph,'results':{},'jobs':[],'candidate_groups':groups,
                  'included_count':sum(p.get('included',True) for p in numbered),
                  'candidate_count':len(remaining_rows),'approved_count':sum(r['status']=='approved' for r in remaining_rows),
                  'paper_numbering_revision':registry.get('numbering_revision'),'exported_at':now()}
        changes[static] = ('window.KG_STATIC='+json.dumps(bundle,ensure_ascii=False).replace('<','\\u003c')+';\n'+teaching).encode('utf-8')
    return numbered, changed


def renumber_papers(allow_paper_list_job: bool = False) -> dict:
    """修复已有空号；已导入数据库时要求Neo4j在线，同步失败不改任何文件。"""
    from src.papers.deletion import deletion_lock, OUTPUTS
    with deletion_lock():
        papers = read_json(DATA/'papers.json', [])
        mapping = contiguous_mapping(papers)
        changed = {old:new for old,new in mapping.items() if old != new}
        if not changed: return {'renumbered':False,'mapping':{},'papers':len(papers)}
        for path in (DATA/'jobs').glob('*.json'):
            if not path.name.endswith('.result.json') and read_json(path,{}).get('status') in ('running','queued'):
                if not (allow_paper_list_job and read_json(path,{}).get('kind') == 'papers'):
                    raise ValueError('后台任务运行中，不能调整论文编号')
        snapshot = read_json(DATA/'graph_snapshot.json', {})
        try: live = store.live_graph()
        except Exception as exc:
            if snapshot.get('paper_ids') or snapshot.get('edges'):
                raise ValueError('请先启动Neo4j再调整编号；尚未修改任何文件') from exc
            live = None
        changes = {}
        numbered,changed = plan_numbering(papers,changes,OUTPUTS)
        new_live = None
        if live and live.get('version'):
            new_live = remap_graph(live,mapping,{p['paper_id']:p['title'] for p in papers})
            changes[DATA/'graph_snapshot.json'] = json_bytes(new_live)
        backup = DATA/'renumbered'/uuid4().hex[:16]
        manifest = {'operation':'renumber','mapping':changed,'time':now(),'neo4j_changed':new_live is not None}
        updated = commit_changes(changes,backup,manifest,live,new_live)
        return {'renumbered':True,'mapping':changed,'papers':len(numbered),'backup':str(backup),'neo4j_updated':updated}
