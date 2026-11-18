/* 类别版本是内容哈希；历史记录ID用于区分同内容的更新/恢复操作。 */
'use strict';
const taxonomyHistoryUI = {listing:null,snapshots:new Map(),selected:null,request:0,restoring:false};
const taxonomyActions = {baseline:'升级前基线',create:'首次生成',update:'更新类别',restore:'恢复版本'};
function taxonomyHistoryTime(value){return new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+'（北京时间）';}
function taxonomyHistoryLabel(row) {
  return `${taxonomyHistoryTime(row.recorded_at)} · ${taxonomyActions[row.action]||row.action} · ${row.version.slice(0,8)}${row.is_current?' · 当前':''}`;
}
async function openTaxonomyHistory() {
  const dialog=$('#taxonomy-history-dialog');if(!dialog.open)dialog.showModal();
  $('#taxonomy-history-error').textContent='';
  const request=++taxonomyHistoryUI.request;
  try {
    const listing=isStatic?(state.taxonomy_history||{versions:[],snapshots:{}}):await api('/api/classification/taxonomy/history');
    if(request!==taxonomyHistoryUI.request)return;
    taxonomyHistoryUI.listing=listing;taxonomyHistoryUI.snapshots=new Map(Object.entries(listing.snapshots||{}));
    const rows=listing.versions;
    $('#taxonomy-history-list').innerHTML=rows.length?`<div class="table-scroll history-timeline"><table><thead><tr><th>记录时间 / 操作</th><th>内容版本</th><th>类别数</th><th>模型 / 来源</th><th>状态</th></tr></thead><tbody>${rows.map(r=>`<tr><td><button type="button" class="text-button" data-history-select="${escapeHTML(r.snapshot_id)}">${escapeHTML(taxonomyHistoryTime(r.recorded_at))} · ${escapeHTML(taxonomyActions[r.action]||r.action)}</button>${r.restored_from?'<small>从 '+escapeHTML(r.restored_from.slice(0,8))+' 恢复</small>':''}</td><td><code title="${escapeHTML(r.version)}">${escapeHTML(r.version.slice(0,12))}</code><small title="${escapeHTML(r.snapshot_id)}">记录 ${escapeHTML(r.snapshot_id.slice(0,8))}</small></td><td>${r.category_count}</td><td>${escapeHTML(r.model||'图谱关系')}</td><td>${r.is_current?'<span class="pill">当前使用</span>':''}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无类别历史。首次分类或更新类别后会开始记录。');
    const options=rows.map(r=>`<option value="${escapeHTML(r.snapshot_id)}">${escapeHTML(taxonomyHistoryLabel(r))}</option>`).join('');
    for(const id of ['taxonomy-history-before','taxonomy-history-after'])$('#'+id).innerHTML=options;
    const current=listing.current_snapshot_id||rows[0]?.snapshot_id;
    if(current){$('#taxonomy-history-after').value=current;$('#taxonomy-history-before').value=rows.find(r=>r.snapshot_id!==current)?.snapshot_id||current;await showTaxonomyHistoryComparison();}
    else{$('#taxonomy-history-detail').innerHTML='';$('#taxonomy-history-comparison').innerHTML='';}
    if(listing.legacy_unarchived)$('#taxonomy-history-error').textContent='当前体系尚未建立历史基线；请更新服务后再查看。';
  } catch(error){if(request===taxonomyHistoryUI.request)$('#taxonomy-history-error').textContent=error.message;}
}
async function taxonomyHistorySnapshot(id) {
  if(taxonomyHistoryUI.snapshots.has(id))return taxonomyHistoryUI.snapshots.get(id);
  const row=await api('/api/classification/taxonomy/history/'+encodeURIComponent(id));
  taxonomyHistoryUI.snapshots.set(id,row);return row;
}
function taxonomyHistoryDiff(before,after) {
  const old=new Map(before.categories.map(c=>[c.id,c])),current=new Map(after.categories.map(c=>[c.id,c]));
  const added=after.categories.filter(c=>!old.has(c.id)),removed=before.categories.filter(c=>!current.has(c.id));
  const fields=['name','dimension','definition','parent_id','entity_ids'];
  const modified=after.categories.filter(c=>old.has(c.id)).map(c=>({before:old.get(c.id),after:c,fields:fields.filter(f=>JSON.stringify(f==='entity_ids'?[...(old.get(c.id)[f]||[])].sort():old.get(c.id)[f])!==JSON.stringify(f==='entity_ids'?[...(c[f]||[])].sort():c[f]))})).filter(c=>c.fields.length);
  const overlaps=(a,b)=>a.dimension===b.dimension&&(a.entity_ids||[]).some(id=>(b.entity_ids||[]).includes(id));
  const merges=after.categories.map(target=>({target,sources:before.categories.filter(c=>overlaps(c,target))})).filter(m=>m.sources.length>=2&&m.sources.some(c=>!current.has(c.id)));
  const splits=before.categories.map(source=>({source,targets:after.categories.filter(c=>overlaps(source,c))})).filter(s=>s.targets.length>=2&&s.targets.some(c=>!old.has(c.id)));
  const merged=new Set(merges.flatMap(m=>m.sources.map(c=>c.id))),split=new Set(splits.flatMap(s=>s.targets.map(c=>c.id)));
  const renames=removed.map(source=>({before:source,targets:added.filter(c=>overlaps(source,c))})).filter(r=>!merged.has(r.before.id)&&r.targets.length===1&&!split.has(r.targets[0].id)&&removed.filter(c=>overlaps(c,r.targets[0])).length===1).map(r=>({before:r.before,after:r.targets[0]}));
  return {added,removed,modified,merges,splits,renames};
}
async function showTaxonomyHistoryComparison() {
  const beforeId=$('#taxonomy-history-before').value,afterId=$('#taxonomy-history-after').value;if(!beforeId||!afterId)return;
  const request=++taxonomyHistoryUI.request;$('#taxonomy-history-error').textContent='';
  try {
    const [before,after]=await Promise.all([taxonomyHistorySnapshot(beforeId),taxonomyHistorySnapshot(afterId)]);
    if(request!==taxonomyHistoryUI.request)return;
    taxonomyHistoryUI.selected=after;
    const a=before.taxonomy,b=after.taxonomy,diff=taxonomyHistoryDiff(a,b);
    const entityNames={...Object.fromEntries((state.graph.nodes||[]).map(n=>[n.id,n.name])),...(after.entity_names||{})};
    const selectedCategories=new Map(b.categories.map(c=>[c.id,c]));
    const names=rows=>rows.map(c=>escapeHTML(c.name)).join('、');
    const fieldNames={name:'名称',dimension:'维度',definition:'定义',parent_id:'父类别',entity_ids:'关联实体'};
    $('#taxonomy-history-comparison').innerHTML=`<h3>类别变化</h3><p>新增 ${diff.added.length} · 删除 ${diff.removed.length} · 修改 ${diff.modified.length}${a.version===b.version?' · 类别内容相同':''}</p>${diff.added.length?`<p><strong>新增：</strong>${names(diff.added)}</p>`:''}${diff.removed.length?`<p><strong>删除：</strong>${names(diff.removed)}</p>`:''}${diff.modified.map(m=>`<details><summary>${escapeHTML(m.after.name)}：${m.fields.map(f=>fieldNames[f]).join('、')}变化</summary>${m.fields.map(f=>f==='entity_ids'?`<p>关联实体：增加 ${(m.after.entity_ids||[]).filter(id=>!(m.before.entity_ids||[]).includes(id)).length}，移除 ${(m.before.entity_ids||[]).filter(id=>!(m.after.entity_ids||[]).includes(id)).length}</p>`:`<p>${fieldNames[f]}：${escapeHTML(m.before[f]||'无')} → ${escapeHTML(m.after[f]||'无')}</p>`).join('')}</details>`).join('')}${diff.merges.map(m=>`<p>疑似合并：${names(m.sources)} → ${escapeHTML(m.target.name)}</p>`).join('')}${diff.splits.map(s=>`<p>疑似拆分：${escapeHTML(s.source.name)} → ${names(s.targets)}</p>`).join('')}${diff.renames.map(r=>`<p>疑似改名：${escapeHTML(r.before.name)} → ${escapeHTML(r.after.name)}</p>`).join('')}<p class="micro">新增、删除及字段变更为精确比较；疑似合并、拆分、改名仅依据关联实体重叠，需结合定义核对。</p>`;
    const impact=after.impact||taxonomyHistoryLocalImpact(after);
    const isCurrent=afterId===taxonomyHistoryUI.listing.current_snapshot_id;
    $('#taxonomy-history-detail').innerHTML=`<h3>所选版本的完整类别</h3><p class="micro">生成于 ${escapeHTML(b.time?taxonomyHistoryTime(b.time):'未知')} · 图谱 ${escapeHTML((b.graph_version||'未知').slice(0,12))} · ${escapeHTML(b.model||'图谱关系')}</p>${Object.entries(autoDimensions).map(([dim,title])=>`<details open><summary>${title}</summary><ul>${b.categories.filter(c=>c.dimension===dim).map(c=>`<li><strong>${escapeHTML(c.name)}</strong> — ${escapeHTML(c.definition)}${c.parent_id?`<p class="micro">父类别：${escapeHTML(selectedCategories.get(c.parent_id)?.name||c.parent_id)}</p>`:''}${c.entity_ids?.length?`<details><summary>关联实体（${c.entity_ids.length}）</summary><p class="micro">${c.entity_ids.map(id=>escapeHTML(entityNames[id]||id)).join('、')}</p></details>`:''}</li>`).join('')||'<li>无类别</li>'}</ul></details>`).join('')}<div class="notice">${impact.graph_outdated?'所选类别来自旧图谱，恢复不会回退图谱。 ':''}按当前论文结果判断：${impact.valid_papers.length} 篇仍匹配，${impact.needs_classification.length} 篇需要分类或重新分类，${impact.outdated_corrections.length} 篇个人修订将不再套用。</div>${impact.needs_classification.length?`<details><summary>需要分类的论文</summary><p>${impact.needs_classification.map(escapeHTML).join('、')}</p></details>`:''}<button type="button" class="primary" id="taxonomy-history-restore" ${isStatic||isCurrent||taxonomyHistoryUI.restoring||!taxonomyHistoryUI.listing.graph_version?'disabled':''}>${isCurrent?'当前使用此版本':'恢复所选类别体系'}</button>${isStatic?'<p class="micro">静态快照可查看历史与差异；恢复需在实时 Demo 操作。</p>':''}`;
  } catch(error){if(request===taxonomyHistoryUI.request)$('#taxonomy-history-error').textContent=error.message;}
}
function taxonomyHistoryLocalImpact(snapshot) {
  const data=automaticUI.data||state.automatic_classification||{papers:[],result:{},corrections:{}};
  const valid=[],needs=[],corrections=[];
  for(const p of data.papers){const r=data.result?.papers?.[p.paper_id],c=data.corrections?.[p.paper_id];const matches=row=>row&&row.graph_version===data.graph_version&&row.taxonomy_version===snapshot.taxonomy.version&&row.paper_sha256===p.sha256;(matches(r)&&r.status==='complete'?valid:needs).push(p.paper_id);if(c&&!matches(c))corrections.push(p.paper_id);}
  return {valid_papers:valid,needs_classification:needs,outdated_corrections:corrections,graph_outdated:snapshot.taxonomy.graph_version!==data.graph_version};
}
async function restoreSelectedTaxonomy() {
  const row=taxonomyHistoryUI.selected,listing=taxonomyHistoryUI.listing;if(!row||isStatic||taxonomyHistoryUI.restoring)return;
  if(!confirm('恢复所选类别体系？当前版本会保留为历史，图谱与论文结果不会回滚。恢复后请按提示重新分类。'))return;
  taxonomyHistoryUI.restoring=true;$('#taxonomy-history-restore').disabled=true;
  try {
    const result=await api('/api/classification/taxonomy/history/'+encodeURIComponent(row.snapshot_id)+'/restore',{method:'POST',body:JSON.stringify({expected_current_snapshot_id:listing.current_snapshot_id,expected_graph_version:listing.graph_version})});
    await loadAutomaticClassification(true);await refresh();await openTaxonomyHistory();notify(`类别已恢复；${result.impact.needs_classification.length} 篇需要分类或重新分类。`);
  } catch(error){$('#taxonomy-history-error').textContent=error.message;}
  finally{taxonomyHistoryUI.restoring=false;const button=$('#taxonomy-history-restore');if(button)button.disabled=isStatic||$('#taxonomy-history-after').value===taxonomyHistoryUI.listing?.current_snapshot_id;}
}
function initTaxonomyHistoryUI() {
  $('#auto-taxonomy-history').onclick=openTaxonomyHistory;
  $('#taxonomy-history-close').onclick=()=>{taxonomyHistoryUI.request++;$('#taxonomy-history-dialog').close();};
  $('#taxonomy-history-before').onchange=showTaxonomyHistoryComparison;$('#taxonomy-history-after').onchange=showTaxonomyHistoryComparison;
  $('#taxonomy-history-list').onclick=event=>{const id=event.target.closest('[data-history-select]')?.dataset.historySelect;if(id){$('#taxonomy-history-after').value=id;showTaxonomyHistoryComparison();}};
  $('#taxonomy-history-detail').onclick=event=>{if(event.target.id==='taxonomy-history-restore')restoreSelectedTaxonomy();};
}
