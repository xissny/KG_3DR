// 先启动Neo4j，在Browser中运行。正式命名空间避免与教学图混淆。
:param project => 'kg3dr-course';
// 1. 局部总览（最多80条边）
MATCH (a:KG3DR {project:$project})-[r]->(b:KG3DR {project:$project})
RETURN a,r,b LIMIT 80;
// 2. 节点类型分布
MATCH (n:KG3DR {project:$project}) RETURN n.type AS entity_type,count(*) AS count;
// 3. 单论文邻域：修改paperId
:param paperId => 'P001';
MATCH path=(p:KG3DR:Paper {project:$project,id:$paperId})-[*1..2]-(n:KG3DR)
WHERE all(v IN nodes(path) WHERE v:KG3DR AND v.project=$project)
RETURN path LIMIT 60;
// 4. 共享组件的论文与方法；共享组件不代表方法继承
MATCH (p1:KG3DR:Paper {project:$project})-[:PROPOSES]->(m1:Method)-[:USES_COMPONENT]->(c:Component)
      <-[:USES_COMPONENT]-(m2:Method)<-[:PROPOSES]-(p2:KG3DR:Paper {project:$project})
WHERE p1.id < p2.id
RETURN p1,m1,c,m2,p2 LIMIT 30;
// 5. 关系对应的原文证据
MATCH (a:KG3DR {project:$project})-[r]->(b:KG3DR {project:$project})
UNWIND r.evidence_ids AS evidence_id
MATCH (e:KGEvidence {project:$project,id:evidence_id})
RETURN a.name,type(r),b.name,e.paper_id,e.page,e.quote LIMIT 30;
// 6. 无来源的关系应为0
MATCH (:KG3DR {project:$project})-[r]->(:KG3DR {project:$project})
WHERE r.evidence_ids IS NULL OR size(r.evidence_ids)=0
RETURN count(r) AS missing_evidence;
