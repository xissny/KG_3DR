# Neo4j / Cypher 入门

启动服务后，打开Browser连接`bolt://localhost:7687`。完整查询见`neo4j/queries.cypher`，样式见`neo4j/style.grass`。

```cypher
// 仅查询正式命名空间，避免把教学图当成正式事实
MATCH (p:KG3DR:Paper {project:'kg3dr-course'}) RETURN p;

// 看一篇论文提出的方法
MATCH (p:KG3DR:Paper {project:'kg3dr-course',id:'P001'})-[:PROPOSES]->(m:Method)
RETURN p,m;

// 关系来源：r.evidence_ids连接独立证据记录
MATCH (a:KG3DR {project:'kg3dr-course'})-[r:USES_COMPONENT]->(b)
UNWIND r.evidence_ids AS eid
MATCH (e:KGEvidence {project:'kg3dr-course',id:eid})
RETURN a.name,b.name,e.paper_id,e.page,e.quote;
```

`MATCH`匹配模式；`WHERE`过滤；`RETURN`选择返回值；`UNWIND`展开列表；`MERGE`在不存在时创建匹配记录。本项目事务替换自己的命名空间，并使用复合唯一性约束，重复导入数量不变。

教学查询将`kg3dr-course`换成`kg3dr-teaching`。请勿手工修改正式库后继续使用旧实验快照；应修改审核源数据再导入，保持可复现。

## 备份与恢复

- 审核源数据：备份`data/papers.json`、`pdfs/`、`parsed/`、`candidates/`、`aliases.json`及标签。
- 图谱交换：`python scripts/09_export_demo.py`导出JSON/CSV/GraphML。
- 重建正式库：启动Neo4j，重新运行阶段04和05。导出的图谱是交换材料，保留源数据才能重新验证证据。
- 不直接复制运行中的Neo4j数据库目录作为备份。
