/* 可直接用Node运行：共享关系只保留勾选论文的证据，不改变原图。 */
const assert = require('node:assert/strict');
const {filterReviewGroups, reviewCounts, filterGraphByPapers} = require('../frontend/filters.js');
const groups = [{id:'T1',rows:[
  {id:'E1',paper_id:'P001',status:'approved'},
  {id:'E2',paper_id:'P001',status:'pending'},
  {id:'E3',paper_id:'P002',status:'pending'},
  {id:'E4',paper_id:'P002',status:'rejected'},
],status_counts:{approved:1,pending:2,rejected:1}}];
const original = JSON.stringify(groups);
assert.deepEqual(filterReviewGroups(groups,'P001','pending')[0].rows.map(r=>r.id),['E2']);
assert.deepEqual(filterReviewGroups(groups,'','approved')[0].status_counts,{pending:0,approved:1,rejected:0});
assert.equal(filterReviewGroups(groups,'P001','rejected').length,0);
assert.deepEqual(reviewCounts(groups,'P002'),{pending:1,approved:0,rejected:1});
assert.equal(JSON.stringify(groups),original);
const graph={nodes:[{id:'M'},{id:'C'},{id:'P001'},{id:'P002'}],edges:[
 {id:'shared',source:'M',target:'C',evidence_ids:['G1','G2'],paper_ids:['P001','P002']},
 {id:'second',source:'P002',target:'M',evidence_ids:['G3'],paper_ids:['P002']},
],evidence:[{id:'G1',paper_id:'P001'},{id:'G2',paper_id:'P002'},{id:'G3',paper_id:'P002'}]};
const frozen = JSON.stringify(graph);
const subset=filterGraphByPapers(graph,['P001']);
assert.deepEqual(subset.edges.map(e=>e.id),['shared']);
assert.deepEqual(subset.edges[0].evidence_ids,['G1']);
assert.deepEqual(subset.edges[0].paper_ids,['P001']);
assert.deepEqual(subset.evidence.map(e=>e.id),['G1']);
assert.deepEqual(subset.nodes.map(n=>n.id),['M','C']);
assert.equal(JSON.stringify(graph),frozen);
assert.equal(filterGraphByPapers(graph,[]).nodes.length,0);
assert.equal(filterGraphByPapers(graph,[]).edges.length,0);
assert.equal(filterGraphByPapers(graph,['unknown']).edges.length,0);
assert.equal(filterGraphByPapers(graph,['P001','P002']).edges.length,2);
// 旧图缺少paper_ids时仍可通过证据追溯，不能误丢共享关系。
assert.equal(filterGraphByPapers({...graph,edges:[{...graph.edges[0],paper_ids:undefined}]},['P001']).edges.length,1);
console.log('审核分组、共享关系证据隔离、空选择、源数据不可变：通过');
