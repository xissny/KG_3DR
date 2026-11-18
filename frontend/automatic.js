/* 图谱自动分类：主流程不依赖人工标签；与高级监督学习实验分开。 */
'use strict';
const autoDimensions = {topic:'研究主题',method:'方法类型',task:'任务类别'};
const autoSourceNames = {direct:'图谱明确记录',inferred:'基于图谱推断',manual:'个人修订'};
const autoStatusNames = {pending:'尚未分类',complete:'分类完成',partial:'部分完成',insufficient:'信息不足',failed:'运行失败',stale:'结果已过期'};
const automaticUI = {data:null,key:null,loading:null,selectionInitialized:false,selected:new Set(),filters:{topic:new Set(),method:new Set(),task:new Set()},visible:[],detail:null,editing:false};

function resetAutomaticSelection() {
  automaticUI.selected.clear();automaticUI.selectionInitialized=false;automaticUI.key=null;automaticUI.data=null;
  automaticUI.detail=null;automaticUI.editing=false;
  if($('#auto-detail-dialog').open)$('#auto-detail-dialog').close();
}
function autoCategoryMap() {return new Map((automaticUI.data?.taxonomy?.categories||[]).map(c=>[c.id,c]));}
function autoRecord(paper) {
  const data=automaticUI.data,row=data.result?.papers?.[paper.paper_id];
  const taxonomy=data.taxonomy||{};
  const stale=!!row && (row.graph_version!==data.graph_version || row.taxonomy_version!==taxonomy.version || row.paper_sha256!==paper.sha256);
  const correction=data.corrections?.[paper.paper_id];
  const currentCorrection=correction && correction.graph_version===data.graph_version && correction.taxonomy_version===taxonomy.version && correction.paper_sha256===paper.sha256;
  const catalogue=autoCategoryMap();
  const assignments=currentCorrection ? correction.category_ids.filter(id=>catalogue.has(id)).map(id=>({category_id:id,dimension:catalogue.get(id).dimension,source:'manual',explanation:correction.note||'用户自行修订；未自动写入图谱。',fact_ids:[],evidence_ids:[]})) : row?.assignments||[];
  const correctedStatus=currentCorrection?(Object.keys(autoDimensions).every(dim=>assignments.some(a=>a.dimension===dim))?'complete':assignments.length?'partial':'insufficient'):null;
  return {row,assignments,correction:currentCorrection?correction:null,status:stale?'stale':correctedStatus||row?.status||'pending',stale};
}
async function loadAutomaticClassification(force=false) {
  const key=[state.automatic_classification_revision,state.graph?.version,state.paper_numbering_revision].join(':');
  if(!force && automaticUI.data && automaticUI.key===key){renderAutoProgress();return;}
  if(automaticUI.loading)return automaticUI.loading;
  automaticUI.loading=(async()=>{
    try {
      const data=isStatic?(state.automatic_classification || {papers:state.papers.filter(p=>p.included!==false && (state.graph.paper_ids||state.graph.nodes.filter(n=>n.type==='Paper').map(n=>n.id)).includes(p.paper_id)),graph_version:state.graph.version,taxonomy:{},result:{},corrections:{}}):await api('/api/classification/automatic');
      automaticUI.data=data;automaticUI.key=key;
      const allowed=new Set(data.papers.map(p=>p.paper_id));
      if(!automaticUI.selectionInitialized){automaticUI.selected=new Set(allowed);automaticUI.selectionInitialized=true;}
      else for(const id of automaticUI.selected)if(!allowed.has(id))automaticUI.selected.delete(id);
      const categoryIds=new Set((data.taxonomy.categories||[]).map(c=>c.id));
      for(const ids of Object.values(automaticUI.filters))for(const id of ids)if(!categoryIds.has(id))ids.delete(id);
      renderAutomaticClassification();
    } finally {automaticUI.loading=null;}
  })();
  return automaticUI.loading;
}
function autoMatchesCategories(assignments) {
  const catalogue=autoCategoryMap(),ids=new Set(assignments.map(a=>a.category_id));
  // 父类别筛选包含子类别，防止细分后上位方向变成空组。
  for(const id of [...ids]){let parent=catalogue.get(id)?.parent_id;const seen=new Set([id]);while(parent&&!seen.has(parent)){ids.add(parent);seen.add(parent);parent=catalogue.get(parent)?.parent_id;}}
  return Object.values(automaticUI.filters).every(selected=>!selected.size || [...selected].some(id=>ids.has(id)));
}
function autoTag(assignment,catalogue) {
  const category=catalogue.get(assignment.category_id);
  return `<span class="auto-tag ${escapeHTML(assignment.source)}" title="${escapeHTML(autoSourceNames[assignment.source]||assignment.source)}">${escapeHTML(category?.name||assignment.category_id)}</span>`;
}
function renderAutoProgress() {
  const active=state.jobs.find(j=>['automatic_classification','classification_taxonomy'].includes(j.kind)&&['queued','running'].includes(j.status));
  const busy=state.jobs.some(j=>['queued','running'].includes(j.status));
  for(const id of ['auto-classify-all','auto-classify-selected','auto-taxonomy-update'])$('#'+id).disabled=isStatic||busy||!automaticUI.data?.papers.length;
  $('#auto-job-progress').textContent=active?`${stageNames[active.kind]} · ${active.logs?.at(-1)?.message||'等待执行'}${active.total?`（${active.completed}/${active.total}）`:''}`:'';
}
function renderAutomaticClassification() {
  const data=automaticUI.data;if(!data)return;
  const records=data.papers.map(p=>autoRecord(p));
  const current=records.filter(r=>r.row&&!r.stale);
  const countMetric=(label,value)=>`<div class="metric"><strong>${value}</strong><span>${label}</span></div>`;
  $('#auto-summary').innerHTML=countMetric('可分类论文',data.papers.length)+countMetric('已有当前结果',current.length)+countMetric('信息不足',current.filter(r=>r.status==='insufficient').length)+countMetric('部分完成',current.filter(r=>r.status==='partial'||r.status==='failed').length);
  const notices=[];
  if(isStatic)notices.push('静态快照仅供浏览、筛选和查看依据；请在实时 Demo 运行分类或保存修改。');
  else if(!data.deepseek_configured)notices.push('未配置 DeepSeek 密钥：仍可整理明确任务关系；主题、方法及补充推断需要配置密钥后重试。');
  if(data.taxonomy_outdated)notices.push('图谱已变化，类别体系仍沿用此前版本。可点击“更新类别体系”吸收新方向，再重新分类。');
  if(records.some(r=>r.stale))notices.push('部分结果已过期，仍可查看历史依据；请重新分类。');
  if(data.taxonomy.source==='graph_fallback')notices.push('当前仅有图谱任务类别，语义类别整理尚未完成。修复配置或网络后更新类别体系。');
  if(data.taxonomy.errors?.length)notices.push(...data.taxonomy.errors);
  if(data.taxonomy.last_rebuild_errors?.length)notices.push('更新类别失败，保留原体系：'+data.taxonomy.last_rebuild_errors.join('；'));
  $('#auto-notice').hidden=!notices.length;$('#auto-notice').textContent=notices.join(' ');
  renderAutoCategories();renderAutoTable();renderAutoProgress();
}
function renderAutoCategories() {
  const data=automaticUI.data,categories=data.taxonomy.categories||[];
  const records=data.papers.map(p=>autoRecord(p));
  const counts=new Map(categories.map(c=>[c.id,records.filter(r=>{
    const ids=new Set(r.assignments.map(a=>a.category_id));const catalogue=autoCategoryMap();
    for(const id of [...ids]){let parent=catalogue.get(id)?.parent_id;const seen=new Set([id]);while(parent&&!seen.has(parent)){ids.add(parent);seen.add(parent);parent=catalogue.get(parent)?.parent_id;}}
    return ids.has(c.id);
  }).length]));
  $('#auto-category-filters').innerHTML=Object.entries(autoDimensions).map(([dim,title])=>`<section><h3>${title}</h3>${categories.filter(c=>c.dimension===dim).map(c=>`<label class="auto-category-option ${c.parent_id?'auto-subcategory':''}" title="${escapeHTML(c.definition)}"><input type="checkbox" data-auto-category="${escapeHTML(c.id)}" data-auto-dimension="${dim}" ${automaticUI.filters[dim].has(c.id)?'checked':''}><span>${escapeHTML(c.name)}</span><small>${counts.get(c.id)||0}</small></label>`).join('')||'<p class="micro">运行分类后自动整理，无需预设标签。</p>'}</section>`).join('');
}
function renderAutoTable() {
  const data=automaticUI.data;if(!data)return;
  const query=$('#auto-search').value.trim().toLowerCase(),status=$('#auto-status').value,catalogue=autoCategoryMap();
  automaticUI.visible=data.papers.filter(p=>{
    const record=autoRecord(p);
    return (p.paper_id+' '+p.title).toLowerCase().includes(query) && (status==='all'||status===record.status) && autoMatchesCategories(record.assignments);
  });
  $('#auto-papers-body').innerHTML=automaticUI.visible.map(p=>{
    const record=autoRecord(p);
    return `<tr><td><input type="checkbox" data-auto-paper="${escapeHTML(p.paper_id)}" aria-label="选择 ${escapeHTML(p.paper_id)}" ${automaticUI.selected.has(p.paper_id)?'checked':''}></td><td><strong>${escapeHTML(p.paper_id)}</strong><div class="auto-paper-title">${escapeHTML(p.title)}</div>${record.correction?'<small>含个人修订</small>':''}</td>${Object.keys(autoDimensions).map(dim=>`<td>${record.assignments.filter(a=>a.dimension===dim).map(a=>autoTag(a,new Map([...(record.row?.category_snapshot||[]).map(c=>[c.id,c]),...catalogue]))).join('')||'<span class="muted">—</span>'}</td>`).join('')}<td><span class="pill ${record.status!=='complete'?'warning':''}">${autoStatusNames[record.status]||record.status}</span><button type="button" data-auto-detail="${escapeHTML(p.paper_id)}">${record.row?'查看依据':'查看详情'}</button></td></tr>`;
  }).join('')||'<tr><td colspan="6">'+empty(data.papers.length?'没有符合筛选条件的论文。':'尚无可分类论文。请先将已审核事实导入正式图谱。')+'</td></tr>';
  updateAutoSelectionCount();
}
function updateAutoSelectionCount() {
  $('#auto-selection-count').textContent=`显示 ${automaticUI.visible.length} / ${automaticUI.data?.papers.length||0} 篇 · 已选 ${automaticUI.selected.size} 篇（含筛选外的选择）`;
  const count=automaticUI.visible.filter(p=>automaticUI.selected.has(p.paper_id)).length;
  $('#auto-select-visible').checked=!!automaticUI.visible.length&&count===automaticUI.visible.length;
  $('#auto-select-visible').indeterminate=count>0&&count<automaticUI.visible.length;
}
async function startAutoClassification(selected) {
  if(isStatic)return notify('静态展示只读，请打开实时 Demo。');
  if(selected&&!automaticUI.selected.size)return notify('请先选择至少一篇论文。');
  try {
    const payload={stage:'automatic_classification',force:$('#auto-force').checked};
    if(selected)payload.paper_ids=[...automaticUI.selected];
    await api('/api/run',{method:'POST',body:JSON.stringify(payload)});
    notify('自动分类已提交，结果逐篇保存，无需人工标签。');await refresh();
  } catch(error){notify(error.message);}
}
function showAutoDetail(paperId) {
  const data=automaticUI.data,paper=data.papers.find(p=>p.paper_id===paperId);if(!paper)return;
  automaticUI.detail=paperId;automaticUI.editing=false;
  const record=autoRecord(paper),row=record.row,catalogue=new Map([...(record.row?.category_snapshot||[]).map(c=>[c.id,c]),...autoCategoryMap()]);
  const context=row?.context||{facts:[],evidence:[],nodes:[]};
  const facts=new Map(context.facts.map(f=>[f.id,f])),evidence=new Map(context.evidence.map(e=>[e.id,e]));
  $('#auto-detail-title').textContent=paper.paper_id+' · '+paper.title;
  $('#auto-detail-content').innerHTML=`${record.stale?'<p class="notice">这是旧版本分类，依据来自当时保存的图谱，请重新运行后再参考。</p>':''}<p class="micro">蓝色：图谱明确记录；紫色：基于图谱推断；绿色：个人修订。引用检查只验证归属与关联，不等于语义已经人工核验。</p>${Object.entries(autoDimensions).map(([dim,title])=>`<section class="auto-dimension-detail"><h3>${title}</h3>${record.assignments.filter(a=>a.dimension===dim).map(a=>`<div class="auto-assignment">${autoTag(a,catalogue)} <small>${escapeHTML(autoSourceNames[a.source])}</small><p>${escapeHTML(a.explanation)}</p>${a.raw_tasks?.length?`<p class="micro">图谱原始任务：${a.raw_tasks.map(escapeHTML).join('、')}</p>`:''}${a.fact_ids.map(fid=>{const f=facts.get(fid);return f?`<div class="auto-path">${escapeHTML(f.subject)} → ${escapeHTML(f.relation)} → ${escapeHTML(f.object)}</div>`:'';}).join('')}${a.evidence_ids.map(eid=>{const e=evidence.get(eid);return e?`<blockquote>${escapeHTML(e.quote)}</blockquote><p class="micro">${escapeHTML(e.paper_id)} · PDF 第 ${e.page} 页 ${!isStatic?`<a href="/api/pdf/${encodeURIComponent(e.paper_id)}#page=${e.page}" target="_blank" rel="noopener">查看原文 ↗</a>`:''}</p>`:'';}).join('')}</div>`).join('')||'<p class="muted">'+(row?'信息不足，未对该维度强行分类。':'尚未运行分类。')+'</p>'}</section>`).join('')}${row?.limitations?`<p class="notice">${escapeHTML(row.limitations)}</p>`:''}${context.truncated?'<p class="notice">事实较多，本次输入保留了优先的100条事实。</p>':''}${row?.errors?.length?`<div class="error">${row.errors.map(escapeHTML).join('<br>')}</div>`:''}<details class="auto-context-details"><summary>查看本次检索的全部图谱事实（${context.facts.length} 条）</summary>${context.facts.map(f=>`<div class="auto-path">${escapeHTML(f.subject)} → ${escapeHTML(f.relation)} → ${escapeHTML(f.object)}</div>`).join('')}</details><div class="button-row"><button type="button" id="auto-edit-correction" ${isStatic||!catalogue.size||record.stale?'disabled':''}>可选：修订分类</button>${record.correction?`<button type="button" id="auto-reset-correction" ${isStatic?'disabled':''}>恢复自动结果</button>`:''}</div><div id="auto-correction-form" hidden></div>`;
  if(!$('#auto-detail-dialog').open)$('#auto-detail-dialog').showModal();
}
function editAutoCorrection() {
  const paper=automaticUI.data.papers.find(p=>p.paper_id===automaticUI.detail),record=autoRecord(paper);
  const ids=new Set(record.assignments.map(a=>a.category_id));automaticUI.editing=true;
  $('#auto-correction-form').hidden=false;
  $('#auto-correction-form').innerHTML=`<p class="micro">个人修订单独保存，不修改图谱或高级实验的训练标签，也不需要填写审核者。</p>${Object.entries(autoDimensions).map(([dim,title])=>`<fieldset><legend>${title}</legend><div class="label-options">${(automaticUI.data.taxonomy.categories||[]).filter(c=>c.dimension===dim).map(c=>`<label><input type="checkbox" data-auto-correction="${escapeHTML(c.id)}" ${ids.has(c.id)?'checked':''}>${escapeHTML(c.name)}</label>`).join('')}</div></fieldset>`).join('')}<label>修改说明（可选）<input id="auto-correction-note" maxlength="2000" value="${escapeHTML(record.correction?.note||'')}"></label><div class="button-row"><button type="button" class="primary" id="auto-save-correction">保存个人修订</button><button type="button" id="auto-cancel-correction">取消</button></div><p id="auto-correction-error" class="error" role="alert"></p>`;
}
async function saveAutoCorrection() {
  const data=automaticUI.data,paper=data.papers.find(p=>p.paper_id===automaticUI.detail),paperId=paper.paper_id;
  const button=$('#auto-save-correction');button.disabled=true;
  try {
    const payload={category_ids:$$('[data-auto-correction]:checked').map(e=>e.dataset.autoCorrection),note:$('#auto-correction-note').value,graph_version:data.graph_version,taxonomy_version:data.taxonomy.version,paper_sha256:paper.sha256};
    await api('/api/classification/automatic/'+encodeURIComponent(paperId),{method:'PUT',body:JSON.stringify(payload)});
    await loadAutomaticClassification(true);showAutoDetail(paperId);notify('个人修订已保存。');
  } catch(error){if($('#auto-correction-error'))$('#auto-correction-error').textContent=error.message;}
  finally{if(button.isConnected)button.disabled=false;}
}
function initAutomaticUI() {
  $('#auto-classify-all').onclick=()=>startAutoClassification(false);
  $('#auto-classify-selected').onclick=()=>startAutoClassification(true);
  $('#auto-reload').onclick=()=>loadAutomaticClassification(true).catch(e=>notify(e.message));
  $('#auto-taxonomy-update').onclick=async()=>{if(!confirm('更新类别体系后，已有分类和个人修订可能过期，需要重新分类。继续吗？'))return;try{await api('/api/run',{method:'POST',body:JSON.stringify({stage:'classification_taxonomy'})});await refresh();notify('已提交类别更新。');}catch(e){notify(e.message);}};
  $('#auto-search').oninput=renderAutoTable;$('#auto-status').onchange=renderAutoTable;
  $('#auto-category-filters').onchange=event=>{const dim=event.target.dataset.autoDimension,id=event.target.dataset.autoCategory;if(!dim)return;if(event.target.checked)automaticUI.filters[dim].add(id);else automaticUI.filters[dim].delete(id);renderAutoTable();};
  $('#auto-clear-filters').onclick=()=>{for(const ids of Object.values(automaticUI.filters))ids.clear();$('#auto-search').value='';$('#auto-status').value='all';renderAutoCategories();renderAutoTable();};
  $('#auto-select-visible').onchange=event=>{for(const p of automaticUI.visible){if(event.target.checked)automaticUI.selected.add(p.paper_id);else automaticUI.selected.delete(p.paper_id);}renderAutoTable();};
  $('#auto-papers-body').onchange=event=>{const id=event.target.dataset.autoPaper;if(!id)return;if(event.target.checked)automaticUI.selected.add(id);else automaticUI.selected.delete(id);updateAutoSelectionCount();};
  $('#auto-papers-body').onclick=event=>{const id=event.target.closest('[data-auto-detail]')?.dataset.autoDetail;if(id)showAutoDetail(id);};
  $('#auto-detail-close').onclick=()=>$('#auto-detail-dialog').close();
  $('#auto-detail-content').onclick=async event=>{
    if(event.target.id==='auto-edit-correction')editAutoCorrection();
    if(event.target.id==='auto-save-correction')await saveAutoCorrection();
    if(event.target.id==='auto-cancel-correction')showAutoDetail(automaticUI.detail);
    if(event.target.id==='auto-reset-correction'){
      const id=automaticUI.detail,data=automaticUI.data,paper=data.papers.find(p=>p.paper_id===id);
      const query=new URLSearchParams({graph_version:data.graph_version,taxonomy_version:data.taxonomy.version,paper_sha256:paper.sha256});
      try{await api('/api/classification/automatic/'+encodeURIComponent(id)+'?'+query,{method:'DELETE'});await loadAutomaticClassification(true);showAutoDetail(id);}catch(e){notify(e.message);}
    }
  };
}
