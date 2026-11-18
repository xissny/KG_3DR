"""Neo4j I/O：事务替换本项目图谱，不触碰其他标签的数据。"""
from __future__ import annotations
import os
from neo4j import GraphDatabase
from src.common.models import RELATION_TYPES
from src.common.storage import DATA, now, read_json, write_json

PROJECT = os.getenv('KG3DR_PROJECT', 'kg3dr-course')
ENTITY_TYPES = {'Paper', 'Method', 'Component', 'Task', 'Representation', 'Dataset', 'Metric'}


def driver():
    password = os.getenv('NEO4J_PASSWORD', '')
    if not password:
        raise ValueError('未配置 Neo4j 密码，请先运行安装脚本')
    return GraphDatabase.driver(os.getenv('NEO4J_URI', 'bolt://127.0.0.1:7687'),
                               auth=(os.getenv('NEO4J_USERNAME', 'neo4j'), password))


def import_graph() -> dict:
    snapshot = read_json(DATA / 'approved_graph.json')
    if not snapshot:
        raise ValueError('缺少核验快照，请先执行阶段 4')
    if not snapshot['edges']:
        raise ValueError('没有已审核关系，不能替换正式图谱')
    from src.review.service import validate_facts
    validate_facts()
    snapshot = read_json(DATA / 'approved_graph.json')
    with driver() as connection:
        connection.verify_connectivity()
        with connection.session() as session:
            for query in [
                'CREATE CONSTRAINT kg3dr_entity IF NOT EXISTS FOR (n:KG3DR) REQUIRE (n.project, n.id) IS UNIQUE',
                'CREATE CONSTRAINT kg3dr_evidence IF NOT EXISTS FOR (e:KGEvidence) REQUIRE (e.project, e.id) IS UNIQUE',
                'CREATE CONSTRAINT kg3dr_meta IF NOT EXISTS FOR (m:KGMeta) REQUIRE m.project IS UNIQUE',
                'CREATE INDEX kg3dr_name IF NOT EXISTS FOR (n:KG3DR) ON (n.name)',
            ]:
                session.run(query).consume()
            session.execute_write(_replace_graph, snapshot)
    write_json(DATA / 'graph_snapshot.json', snapshot)
    return {'version': snapshot['version'], 'nodes': len(snapshot['nodes']), 'edges': len(snapshot['edges'])}


def _replace_graph(tx, snapshot):
    # 在同一事务内替换，只清理本项目自己的节点；失败时原图保留。
    tx.run('MATCH (n:KG3DR {project:$p}) DETACH DELETE n', p=PROJECT).consume()
    tx.run('MATCH (n:KGEvidence {project:$p}) DETACH DELETE n', p=PROJECT).consume()
    for kind in ENTITY_TYPES:
        rows = [n for n in snapshot['nodes'] if n['type'] == kind]
        tx.run(f'UNWIND $rows AS row CREATE (n:KG3DR:{kind}) SET n = row, n.project=$p', rows=rows, p=PROJECT).consume()
    tx.run('UNWIND $rows AS row CREATE (e:KGEvidence) SET e = row, e.project=$p', rows=snapshot['evidence'], p=PROJECT).consume()
    for relation in RELATION_TYPES:
        rows = [edge for edge in snapshot['edges'] if edge['relation'] == relation]
        # 关系类型来自固定白名单，不能由用户字符串拼接。
        tx.run(f'''UNWIND $rows AS row MATCH (a:KG3DR {{id:row.source, project:$p}}),
                   (b:KG3DR {{id:row.target, project:$p}})
                   CREATE (a)-[r:{relation}]->(b)
                   SET r.id=row.id, r.evidence_ids=row.evidence_ids, r.paper_ids=row.paper_ids''', rows=rows, p=PROJECT).consume()
    tx.run('''MATCH (e:KGEvidence {project:$p}), (paper:KG3DR:Paper {project:$p})
              WHERE e.paper_id=paper.id MERGE (e)-[:FROM_PAPER]->(paper)''', p=PROJECT).consume()
    metadata = {key: snapshot[key] for key in ['version', 'created_at', 'paper_ids', 'teaching']}
    tx.run('MERGE (m:KGMeta {project:$p}) SET m += $metadata', p=PROJECT, metadata=metadata).consume()


def live_graph() -> dict:
    with driver() as connection, connection.session() as session:
        metadata = session.run('MATCH (m:KGMeta {project:$p}) RETURN properties(m) AS m', p=PROJECT).single()
        if not metadata:
            return {'nodes': [], 'edges': [], 'evidence': [], 'version': None, 'paper_ids': [], 'source': 'neo4j'}
        nodes = [dict(row['n']) for row in session.run('MATCH (n:KG3DR {project:$p}) RETURN properties(n) AS n', p=PROJECT)]
        edges = [dict(row['r'], source=row['source'], target=row['target'], relation=row['relation']) for row in session.run(
            'MATCH (a:KG3DR {project:$p})-[r]->(b:KG3DR {project:$p}) RETURN properties(r) AS r,a.id AS source,b.id AS target,type(r) AS relation', p=PROJECT)]
        evidence = [dict(row['e']) for row in session.run('MATCH (e:KGEvidence {project:$p}) RETURN properties(e) AS e', p=PROJECT)]
        return {**dict(metadata['m']), 'nodes': nodes, 'edges': edges, 'evidence': evidence, 'source': 'neo4j'}


def load_snapshot() -> dict:
    graph = read_json(DATA / 'graph_snapshot.json')
    if not graph or not graph['edges']:
        raise ValueError('缺少已导入图谱，请先审核并导入 Neo4j')
    return graph
