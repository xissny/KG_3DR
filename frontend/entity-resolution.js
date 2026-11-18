/* 实体消歧：修改只留在表单或草稿中，逐组确认才写入别名。 */
'use strict';
const resolutionUI = {data:null, key:null, loading:null, dirty:false, busy:false, edits:new Map()};

async function loadEntityResolution(force=false) {
  if(resolutionUI.loading)return resolutionUI.loading;
  if(!force && resolutionUI.data && resolutionUI.key===state.revision){renderResolutionProgress();return;}
  if((resolutionUI.dirty||resolutionUI.busy) && !force){renderResolutionProgress();return;}
  resolutionUI.loading=(async()=>{
    const data=isStatic?(window.KG_STATIC?.entity_resolution||state.entity_resolution||{entities:[],suggestions:[],run:null}):await api('/api/entity-resolution');
    resolutionUI.data=data;resolutionUI.key=state.revision;resolutionUI.dirty=false;resolutionUI.edits.clear();
    renderEntityResolution();
  })();
  try {await resolutionUI.loading;} finally {resolutionUI.loading=null;}
}
function renderResolutionProgress() {
  const job=state.jobs.find(j=>j.kind==='entity_resolution'&&['queued','running'].includes(j.status));
  const busy=resolutionUI.busy||state.jobs.some(j=>['queued','running'].includes(j.status));
  $('#resolution-detect').disabled=isStatic||busy;
  $('#resolution-force').disabled=isStatic||busy;
  $('#resolution-reload').disabled=resolutionUI.busy;
  $$('#resolution-list [data-resolution-action]').forEach(el=>el.disabled=isStatic||busy||el.dataset.stale==='true');
  const run=resolutionUI.data?.run;
  $('#resolution-progress').textContent=job?`AI 检测中 · ${job.logs?.at(-1)?.message||'等待执行'}${job.total?`（${job.completed}/${job.total}）`:''}`:
    run?`最近检测：${run.completed}/${run.total} 批${run.status==='partial'?' · 部分失败，可重试':run.status==='running'?' · 执行中或已中断，可重试':''} · ${resolutionUI.data.entities.length} 个已通过实体`:'审核三元组后，点击检测生成合并建议。';
  const ignored=(run?.warnings||[]).reduce((sum,w)=>sum+(w.ignored||0),0);
  $('#resolution-notice').hidden=!ignored;
  $('#resolution-notice').textContent=ignored?`已忽略 ${ignored} 条无效合并建议，其余结果可正常审核。`:'';
  if(resolutionUI.dirty)$('#resolution-progress').textContent+=' · 有未保存的编辑；点击刷新建议将丢弃这些编辑。';
}
function resolutionEvidence(entity) {
  return `<details><summary>${escapeHTML(entity.name)} · ${entity.evidence.length} 条来源证据</summary>${entity.evidence.map(e=>`<div class="evidence-record"><strong>${escapeHTML(e.paper_id)} · ${escapeHTML(e.paper_title)} · 第 ${escapeHTML(e.page)} 页</strong><small>${escapeHTML(e.relation)} · ${escapeHTML(e.other.name)}</small><blockquote>${escapeHTML(e.quote)}</blockquote></div>`).join('')}</details>`;
}
function renderEntityResolution() {
  const data=resolutionUI.data;if(!data)return;
  const status=$('#resolution-status').value;
  const rows=data.suggestions.filter(r=>status==='all'||(status==='pending'?(!r.stale&&['pending','draft'].includes(r.status)):status==='stale'?r.stale:r.status===status));
  const labels={pending:'待审核',draft:'已保存草稿',confirmed:'已合并',rejected:'已拒绝'};
  $('#resolution-error').textContent=(data.run?.errors||[]).map(e=>`${e.type} 第 ${e.batch} 批：${e.error}`).join('；');
  $('#resolution-list').innerHTML=rows.map(row=>{
    const editable=['pending','draft'].includes(row.status)&&!row.stale&&!isStatic;
    const edit=resolutionUI.edits.get(row.id);
    const members=edit?edit.all_ids.map(id=>data.entities.find(e=>e.id===id)||row.members.find(e=>e.id===id)).filter(Boolean):row.members;
    const selected=edit?edit.member_ids:row.member_ids;
    return `<section class="resolution-group" data-resolution-id="${escapeHTML(row.id)}"><div class="card-heading"><h3>${escapeHTML(row.type)} · ${escapeHTML(labels[row.status])}</h3>${row.stale?'<span class="pill warning">实体或证据已变化，请重新检测</span>':''}</div><p>${escapeHTML(row.reason)}</p><p class="micro">AI 初始建议：${escapeHTML(row.original.canonical_name)}${row.model?' · '+escapeHTML(row.model):''}</p>
      <div class="resolution-members">${members.map(e=>`<label class="resolution-member"><input type="checkbox" data-resolution-member value="${escapeHTML(e.id)}" ${selected.includes(e.id)?'checked':''} ${editable?'':'disabled'}><span>${escapeHTML(e.name)}</span></label>`).join('')}</div>
      ${editable?`<label>搜索并添加同类型实体<input type="search" data-resolution-search placeholder="输入名称筛选"></label><select data-resolution-add aria-label="选择要添加的实体"><option value="">选择要添加的实体</option>${data.entities.filter(e=>e.type===row.type&&!members.some(member=>member.id===e.id)).map(e=>`<option value="${escapeHTML(e.id)}">${escapeHTML(e.name)}</option>`).join('')}</select>`:''}
      <label>合并为标准名称<input data-resolution-name maxlength="300" value="${escapeHTML(edit?.canonical_name??row.canonical_name)}" ${editable?'':'disabled'}></label><label>审核备注<input data-resolution-note maxlength="2000" value="${escapeHTML(edit?.note??row.note??'')}" ${editable?'':'disabled'}></label>
      <div class="resolution-evidence">${members.map(resolutionEvidence).join('')}</div>
      ${editable?`<div class="button-row"><button data-resolution-action="draft">保存草稿</button><button class="primary" data-resolution-action="confirm">确认合并</button><button data-resolution-action="reject">拒绝合并</button></div>`:`<p class="micro">${escapeHTML(row.reviewer||'')} ${escapeHTML(row.reviewed_at||'')}${row.status==='confirmed'?' · 别名已保存；通过校验与导入更新正式图谱。':''}</p>`}
      <p class="error resolution-error" role="alert"></p></section>`;
  }).join('')||empty(data.run?'当前筛选没有合并建议。':'尚无检测结果。');
  renderResolutionProgress();
}
function captureResolutionEdit(element) {
  const card=element.closest('[data-resolution-id]');if(!card)return;
  resolutionUI.edits.set(card.dataset.resolutionId,{
    all_ids:[...card.querySelectorAll('[data-resolution-member]')].map(el=>el.value),
    member_ids:[...card.querySelectorAll('[data-resolution-member]:checked')].map(el=>el.value),
    canonical_name:card.querySelector('[data-resolution-name]').value,
    note:card.querySelector('[data-resolution-note]').value
  });
  resolutionUI.dirty=true;renderResolutionProgress();
}
function initEntityResolution() {
  $('#resolution-detect').onclick=async()=>{
    if(resolutionUI.dirty){notify('请先保存草稿，或点击刷新建议放弃编辑。');return;}
    await runStage('entity_resolution',{force:$('#resolution-force').checked});
  };
  $('#resolution-reload').onclick=()=>loadEntityResolution(true).catch(e=>notify(e.message));
  $('#resolution-status').onchange=renderEntityResolution;
  $('#resolution-list').oninput=event=>{
    if(!event.target.matches('[data-resolution-search]'))captureResolutionEdit(event.target);
    if(event.target.matches('[data-resolution-search]')) {
      const select=event.target.closest('[data-resolution-id]').querySelector('[data-resolution-add]');
      const query=event.target.value.trim().toLowerCase();
      [...select.options].forEach(option=>option.hidden=!!option.value&&!option.textContent.toLowerCase().includes(query));
    }
  };
  $('#resolution-list').onchange=event=>{
    if(!event.target.matches('[data-resolution-add]')||!event.target.value){captureResolutionEdit(event.target);return;}
    const card=event.target.closest('[data-resolution-id]');
    const entity=resolutionUI.data.entities.find(e=>e.id===event.target.value);
    if(!entity)return;
    card.querySelector('.resolution-members').insertAdjacentHTML('beforeend',`<label class="resolution-member"><input type="checkbox" data-resolution-member value="${escapeHTML(entity.id)}" checked><span>${escapeHTML(entity.name)}</span></label>`);
    card.querySelector('.resolution-evidence').insertAdjacentHTML('beforeend',resolutionEvidence(entity));
    event.target.selectedOptions[0].remove();event.target.value='';captureResolutionEdit(event.target);
  };
  $('#resolution-list').onclick=async event=>{
    const button=event.target.closest('[data-resolution-action]');if(!button||resolutionUI.busy)return;
    const card=button.closest('[data-resolution-id]'),error=card.querySelector('.resolution-error');
    const payload={revision:resolutionUI.data.revision,action:button.dataset.resolutionAction,
      member_ids:[...card.querySelectorAll('[data-resolution-member]:checked')].map(el=>el.value),
      canonical_name:card.querySelector('[data-resolution-name]').value.trim(),
      reviewer:$('#resolution-reviewer').value.trim(),note:card.querySelector('[data-resolution-note]').value};
    error.textContent='';
    if(payload.member_ids.length<2){error.textContent='请选择至少两个不同的实体。';return;}
    if(!payload.canonical_name){error.textContent='标准名称不可为空。';return;}
    if(payload.action!=='draft'&&!payload.reviewer){error.textContent='请在上方填写审核者姓名。';return;}
    resolutionUI.busy=true;card.querySelectorAll('input,select').forEach(el=>el.disabled=true);renderResolutionProgress();
    try {
      const data=await api('/api/entity-resolution/'+encodeURIComponent(card.dataset.resolutionId),{method:'PUT',body:JSON.stringify(payload)});
      resolutionUI.data=data;resolutionUI.edits.delete(card.dataset.resolutionId);resolutionUI.dirty=resolutionUI.edits.size>0;renderEntityResolution();
      if(payload.action==='confirm'){await loadCandidates();if(graphMode==='candidate')showCandidateGraph();}
      await refresh();
      notify(payload.action==='confirm'?'合并已保存，请校验并导入正式图谱。':payload.action==='draft'?'草稿已保存。':'已拒绝此合并建议。');
    }catch(e){error.textContent=e.message;card.querySelectorAll('input,select').forEach(el=>el.disabled=false);}
    finally {resolutionUI.busy=false;renderResolutionProgress();}
  };
}
