/* 展示筛选的纯函数：不修改源数据，供实时页面、离线页面和测试共同使用。 */
(function(root) {
  'use strict';
  const reviewLabels = {pending: '待审核', approved: '已通过', rejected: '已拒绝'};

  function filterReviewGroups(groups, paperId = '', status = 'pending') {
    // 必须先筛证据再重算分组，不能把同一三元组的通过状态传播给其他证据。
    return groups.flatMap(group => {
      const rows = group.rows.filter(row => (!paperId || row.paper_id === paperId) &&
        (!status || row.status === status));
      if (!rows.length) return [];
      const status_counts = {pending: 0, approved: 0, rejected: 0};
      rows.forEach(row => { status_counts[row.status] += 1; });
      return [{...group, rows, status_counts}];
    });
  }

  function reviewCounts(groups, paperId = '') {
    const counts = {pending: 0, approved: 0, rejected: 0};
    groups.forEach(group => group.rows.forEach(row => {
      if (!paperId || row.paper_id === paperId) counts[row.status] += 1;
    }));
    return counts;
  }

  function filterGraphByPapers(graph, paperIds) {
    const selected = new Set(paperIds);
    const evidence = (graph.evidence || []).filter(row => selected.has(row.paper_id));
    const evidenceById = new Map(evidence.map(row => [row.id, row]));
    const edges = (graph.edges || []).flatMap(edge => {
      const evidence_ids = (edge.evidence_ids || []).filter(id => evidenceById.has(id));
      const paper_ids = [...new Set([
        ...(edge.paper_ids || []).filter(id => selected.has(id)),
        ...evidence_ids.map(id => evidenceById.get(id).paper_id),
      ])];
      if (!paper_ids.length) return [];
      return [{...edge, evidence_ids, paper_ids}];
    });
    const nodeIds = new Set(edges.flatMap(edge => [edge.source, edge.target]));
    const evidenceIds = new Set(edges.flatMap(edge => edge.evidence_ids));
    return {...graph, nodes: (graph.nodes || []).filter(node => nodeIds.has(node.id)),
      edges, evidence: evidence.filter(row => evidenceIds.has(row.id)),
      paper_ids: [...selected]};
  }

  const functions = {reviewLabels, filterReviewGroups, reviewCounts, filterGraphByPapers};
  root.KGFilters = functions;
  if (typeof module !== 'undefined' && module.exports) module.exports = functions;
})(globalThis);
