/* 三类任务、逐结论证据与表单化评测；静态快照只读。 */
'use strict';
const generationTasks = {
  qa:{label:'问题回答', input:'自然语言问题，可选实体锚点及论文范围。', output:'直接回答、可核查结论、论文来源与证据不足说明。', graph:'识别标准名与已确认别名，检索两跳子图，分别汇集比较对象的事实。', evaluation:'回答正确率、参考要点覆盖率、引用准确率、结论证据支持率、正确拒答率。', placeholder:'例如：选择两个方法，提问它们共享哪些组件、输出表示有何差异？'},
  summary:{label:'主题总结', input:'选择需要总结的论文（至少一篇），即可直接生成。', output:'主题概述、相关方法、共性与差异、数据集与评价指标、资料缺口。', graph:'汇集所选论文支持的全部核验事实，归纳主题与方法，按技术维度组织。', evaluation:'关键事实覆盖率、主题相关性、组织清晰度、跨论文综合质量、引用准确率与证据支持率。', placeholder:'例如：选择一个任务或组件，概括相关方法的技术联系与差异。'},
  review:{label:'研究方向综述', input:'选择需要综述的论文（至少一篇），即可直接生成。', output:'方向概述、技术路线、代表工作、现有证据与局限，以及单独标记的未来研究建议。', graph:'汇集所选论文支持的核验事实，梳理方向与技术路线；建议必须关联已有结论。', evaluation:'代表工作与技术路线覆盖率、比较准确性、综合分析质量、建议合理性、引用准确率与证据支持率。', placeholder:'例如：围绕所选任务梳理技术路线，并提出有事实依据、尚待验证的研究建议。'}
};
const generationQuestionTemplates = [
  {id:'components', label:'了解技术组件', types:['Method'], relation:'USES_COMPONENT', question:n=>`“${n[0]}”采用了哪些技术组件？请逐项列出支撑事实和论文来源。`},
  {id:'outputs', label:'查看输出表示', types:['Method'], relation:'OUTPUTS', question:n=>`“${n[0]}”输出什么三维表示？请给出图谱事实和论文原文依据。`},
  {id:'tasks', label:'了解解决的任务', types:['Method'], relation:'SOLVES', question:n=>`“${n[0]}”解决哪些任务？分别有哪些论文证据支持？`},
  {id:'datasets', label:'查看评测数据集', types:['Method'], relation:'EVALUATED_ON', question:n=>`“${n[0]}”在哪些数据集上进行评测？请区分训练数据与评测数据，并标明出处。`},
  {id:'metrics', label:'了解评价指标', types:['Method'], relation:'USES_METRIC', question:n=>`“${n[0]}”使用哪些评价指标？请给出支持事实与论文来源；未记录时说明证据不足。`},
  {id:'compare', label:'比较两种方法', types:['Method','Method'], relation:'USES_COMPONENT', question:n=>`“${n[0]}”与“${n[1]}”在技术组件和输出表示上有哪些共同点与差异？请分别引用证据。`},
  {id:'task-methods', label:'查找同任务方法', types:['Task'], relation:'SOLVES', question:n=>`图谱中哪些方法或论文研究“${n[0]}”？请列出对应关系与论文来源。`},
  {id:'component-papers', label:'追踪组件来源', types:['Component'], relation:'USES_COMPONENT', question:n=>`哪些方法采用了“${n[0]}”？这些方法由哪些论文提出？请展示关联事实及来源。`},
];
let generationTemplateId=null, generationTemplateEntityIds=[];
const generationEntityTypeLabels={Method:'方法',Task:'任务',Component:'组件'};
function currentGenerationTemplate(){return generationQuestionTemplates.find(t=>t.id===generationTemplateId);}
function generationTemplateEntities(template){
  return template.types.map((type,i)=>state.graph.nodes.find(n=>n.id===generationTemplateEntityIds[i]&&n.type===type));
}
function updateGenerationTemplateQuestion(){
  const template=currentGenerationTemplate();if(generationTask!=='qa'||!template)return;
  const entities=generationTemplateEntities(template);
  generationEntities=new Set(entities.filter(Boolean).map(n=>n.id));
  const complete=entities.every(Boolean)&&new Set(entities.map(n=>n.id)).size===entities.length;
  $('#question').value=complete?template.question(entities.map(n=>n.name)):'';
  $('#question').placeholder=template.question(template.types.map((type,i)=>generationEntityTypeLabels[type]+(template.types.length>1?String.fromCharCode(65+i):'')));
  $('#generation-input-error').textContent='';
}
function renderGenerationTemplates(){
  const template=currentGenerationTemplate(), active=generationTask==='qa'&&!!template;
  $('#generation-template-panel').hidden=generationTask!=='qa';
  $('#generation-custom-question').setAttribute('aria-pressed',String(!template));
  $('#generation-question-templates').innerHTML=generationQuestionTemplates.map(item=>{
    const placeholders=item.types.map((type,i)=>generationEntityTypeLabels[type]+(item.types.length>1?String.fromCharCode(65+i):''));
    return `<button type="button" data-question-template="${item.id}" aria-pressed="${item.id===generationTemplateId}"><strong>${escapeHTML(item.label)}</strong><span>${escapeHTML(item.question(placeholders))}</span></button>`;
  }).join('');
  $('#generation-template-entities').hidden=!template;
  $('#generation-anchor-controls').hidden=generationTask!=='qa'||active;
  $('#generation-question-controls').hidden=generationTask!=='qa';
  $('#generation-paper-hint').textContent=generationTask==='qa'?'不选表示全部正式入图论文':'至少选择一篇论文，直接生成';
  $('#generation-question-label').textContent=active?'自动生成的问题（可修改）':generationTask==='qa'?'你想了解什么？':'描述主题与关注问题';
  if(!template)return;
  const entities=generationTemplateEntities(template);
  const invalid=generationTemplateEntityIds.some((id,i)=>id&&!entities[i]);
  if(invalid){generationTemplateEntityIds=entities.map(n=>n?.id||'');updateGenerationTemplateQuestion();}
  $('#generation-template-entities').innerHTML=template.types.map((type,i)=>{
    const label=generationEntityTypeLabels[type]+(template.types.length>1?String.fromCharCode(65+i):'');
    const options=state.graph.nodes.filter(n=>n.type===type).sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'));
    return `<label>${escapeHTML(label)}<select data-template-entity="${i}" aria-label="选择${escapeHTML(label)}"><option value="">请选择${escapeHTML(label)}</option>${options.map(n=>`<option value="${escapeHTML(n.id)}" ${generationTemplateEntityIds[i]===n.id?'selected':''} ${generationTemplateEntityIds.some((id,j)=>i!==j&&id===n.id)?'disabled':''}>${escapeHTML(n.name)}</option>`).join('')}</select>${options.length?'':'<span class="muted">图谱暂无此类实体，请先导入相关事实。</span>'}</label>`;
  }).join('');
}
let generationTask='qa', generationEntities=new Set(), generationPapers=new Set(), generationOptionsStamp='', generationResultStamp='', generationCy=null;
const generationScoreLabels={relevance:'主题相关性',organization:'组织清晰度',synthesis:'跨论文综合质量',comparison:'技术比较准确性',suggestion_quality:'建议合理性'};
const generationCountLabels={claims_total:'事实性结论总数',supported_claims:'有充分证据支持的结论数',citations_total:'引用总数',correct_citations:'正确引用数',key_points_total:'参考要点总数',covered_key_points:'覆盖参考要点数'};
function initGenerationUI(){
  $$('[data-generation-task]').forEach(button=>button.onclick=()=>{generationTask=button.dataset.generationTask;updateGenerationGuide();updateGenerationTemplateQuestion();renderGeneration();});
  $('#generation-question-templates').onclick=event=>{
    const button=event.target.closest('[data-question-template]');if(!button)return;
    if(generationTemplateId!==button.dataset.questionTemplate){
      generationTemplateId=button.dataset.questionTemplate;generationTemplateEntityIds=[];
      updateGenerationTemplateQuestion();
    }
    renderGenerationOptions(true);
    $('#generation-template-entities select')?.focus();
  };
  $('#generation-template-entities').onchange=event=>{
    const select=event.target.closest('[data-template-entity]');if(!select)return;
    generationTemplateEntityIds[Number(select.dataset.templateEntity)]=select.value;
    updateGenerationTemplateQuestion();renderGenerationOptions(true);
  };
  $('#generation-custom-question').onclick=()=>{
    generationTemplateId=null;generationTemplateEntityIds=[];
    renderGenerationOptions(true);$('#question').placeholder=generationTasks.qa.placeholder;$('#question').focus();
  };
  $('#generation-entity-search').oninput=()=>renderGenerationOptions(true);
  $('#generation-entities').onchange=event=>{const box=event.target;if(box.matches('input[type=checkbox]')){box.checked?generationEntities.add(box.value):generationEntities.delete(box.value);renderGenerationTemplates();}};
  $('#generation-papers').onchange=event=>{const box=event.target;if(box.matches('input[type=checkbox]')){box.checked?generationPapers.add(box.value):generationPapers.delete(box.value);renderGenerationTemplates();}};
  updateGenerationGuide();
}
function updateGenerationGuide(){
  const config=generationTasks[generationTask];
  renderGenerationTemplates();
  $$('[data-generation-task]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.generationTask===generationTask)));
  $('#generation-guide').innerHTML=['input','output','graph','evaluation'].map((key,i)=>`<div><strong>${['输入','输出','图谱如何参与','如何评价'][i]}</strong><p>${escapeHTML(config[key])}</p></div>`).join('');
  $('#question').placeholder=config.placeholder;$('#generation-question-label').textContent=generationTask==='qa'&&currentGenerationTemplate()?'自动生成的问题（可修改）':generationTask==='qa'?'你想了解什么？':'描述主题与关注问题';
  $('#generation-anchor-hint').textContent=generationTask==='qa'?'可选':'至少选择一个';
  $('#ask-button').textContent=`生成${config.label} ↗`;$('#generation-input-error').textContent='';
}
function renderGenerationOptions(force=false){
  const signature=JSON.stringify([state.graph.version,state.aliases,state.graph.nodes,state.papers.map(p=>[p.paper_id,p.title]),state.paper_numbering_revision]);
  if(signature!==generationOptionsStamp){
    const valid=new Set(state.graph.nodes.map(n=>n.id)), papers=new Set(state.graph.paper_ids||state.graph.nodes.filter(n=>n.type==='Paper').map(n=>n.id));
    generationEntities=new Set([...generationEntities].filter(id=>valid.has(id)));generationPapers=new Set([...generationPapers].filter(id=>papers.has(id)));
    $('#generation-papers').innerHTML=state.papers.filter(p=>papers.has(p.paper_id)).map(p=>`<label><input type="checkbox" value="${escapeHTML(p.paper_id)}" ${generationPapers.has(p.paper_id)?'checked':''}><span>${escapeHTML(p.paper_id+' · '+p.title)}</span></label>`).join('')||'<p class="muted">暂无正式入图论文</p>';
    generationOptionsStamp=signature;force=true;
  }
  if(!force)return;
  renderGenerationTemplates();
  const query=$('#generation-entity-search').value.trim().toLocaleLowerCase();
  const nodes=state.graph.nodes.filter(n=>generationEntities.has(n.id)||[n.name,n.id,...Object.entries(state.aliases||{}).filter(([key,v])=>key.startsWith(n.type+':')&&v===n.name).map(([key])=>key.split(':').slice(1).join(':'))].some(v=>v.toLocaleLowerCase().includes(query)));
  $('#generation-entities').innerHTML=nodes.map(n=>`<label><input type="checkbox" value="${escapeHTML(n.id)}" ${generationEntities.has(n.id)?'checked':''}><span>${escapeHTML(n.name)} <small>${escapeHTML(n.type)}</small></span></label>`).join('')||'<p class="muted">没有匹配的正式图谱实体</p>';
}
async function submitGeneration(){
  const error=$('#generation-input-error');error.textContent='';
  if(isStatic)return notify('当前为静态展示。请启动服务器后生成。');
  const template=generationTask==='qa'?currentGenerationTemplate():null;
  if(template&&!generationTemplateEntities(template).every(Boolean)){error.textContent='请先选择模板要求的实体，系统会自动生成完整问题。';return;}
  if(generationTask==='qa'&&!$('#question').value.trim()){error.textContent='请先输入问题。';return;}
  if(generationTask!=='qa'&&!generationPapers.size){error.textContent='请至少选择一篇论文，再直接生成。';return;}
  $('#ask-button').disabled=true;
  const payload={task_type:generationTask,paper_ids:[...generationPapers],force:$('#generation-force').checked};
  if(generationTask==='qa'){payload.question=$('#question').value;payload.entity_ids=[...generationEntities];}
  try{await runStage('ask',payload);}
  finally{$('#ask-button').disabled=false;}
}
function generationSourceHTML(source,context){
  const paper=context.papers?.find(p=>p.paper_id===source.paper_id)||state.papers.find(p=>p.paper_id===source.paper_id);
  const validPage=Number.isInteger(source.page)&&source.page>0;
  return `<div class="evidence-record"><strong>${escapeHTML(source.paper_id)} · ${escapeHTML(paper?.title||source.paper_id)}</strong><p>PDF 第 ${escapeHTML(source.page)} 页 · ${escapeHTML(source.id)} ${!isStatic&&validPage?`<a target="_blank" rel="noopener" href="/api/pdf/${encodeURIComponent(source.paper_id)}#page=${source.page}">打开论文 ↗</a>`:''}</p><blockquote>${escapeHTML(source.quote)}</blockquote></div>`;
}
function generationClaimHTML(claim,index,context,prefix){
  const nodes=new Map((context.nodes||[]).map(n=>[n.id,n.name]));
  return `<article class="claim" id="${prefix}-${index}"><p><strong>[${index+1}]</strong> ${escapeHTML(claim.text)}</p><details><summary>查看支撑事实与论文来源 · ${(claim.sources||[]).length} 条原文</summary>${(claim.fact_ids||[]).map(fid=>{const f=context.edges?.find(e=>e.id===fid);return `<p><code>${escapeHTML(fid)}</code>${f?`<br>${escapeHTML(nodes.get(f.source)||f.source)} → ${escapeHTML(f.relation)} → ${escapeHTML(nodes.get(f.target)||f.target)}`:''}</p>`;}).join('')}${(claim.sources||[]).map(source=>generationSourceHTML(source,context)).join('')}</details></article>`;
}
function generationAnswerHTML(result,prefix='generation-claim'){
  const context=result.context||{}, answer=result.answer||{}, claims=answer.claims||[], indices=new Map(claims.map((c,i)=>[c.id,i]));
  const rendered=new Set();
  const sections=(answer.sections||[]).map(section=>{
    const members=(section.claim_ids||[]).filter(id=>indices.has(id)&&!rendered.has(id));members.forEach(id=>rendered.add(id));
    return members.length?`<section><h3>${escapeHTML(section.title)}</h3>${members.map(id=>generationClaimHTML(claims[indices.get(id)],indices.get(id),context,prefix)).join('')}</section>`:'';
  }).join('');
  const remaining=claims.map((c,i)=>rendered.has(c.id)?'':generationClaimHTML(c,i,context,prefix)).join('');
  return `${sections}${remaining}${!claims.length?empty('当前没有可展示的有证据结论。'):''}${(answer.suggestions||[]).length?`<section class="generation-suggestions"><h3>未来研究建议 · 推断，尚待验证</h3>${answer.suggestions.map(s=>`<article><h4>${escapeHTML(s.text)}</h4><p>依据：${s.claim_ids.filter(id=>indices.has(id)).map(id=>`<a href="#${prefix}-${indices.get(id)}" data-claim-link="${prefix}-${indices.get(id)}">[${indices.get(id)+1}]</a>`).join(' ')}</p><p>推理说明：${escapeHTML(s.reasoning)}</p><p>待验证问题：${escapeHTML(s.uncertainty)}</p></article>`).join('')}</section>`:''}<p class="notice">${escapeHTML(answer.limitations||'请结合原文核验语义支持。')}</p><p class="muted">${escapeHTML(answer.citation_check||'引用结构检查不替代语义判断')}；已移除 ${answer.rejected_claims?.length||0} 条无效结论。</p>`;
}
function renderGeneration(){
  renderGenerationOptions();
  const legacy=state.results.generation_latest;
  const result=state.results.generation_by_task?.[generationTask] || (legacy&&!legacy.is_evaluation&&(legacy.task_type||'qa')===generationTask?legacy:null);
  const evaluation=state.results.generation_evaluation;
  const stamp=JSON.stringify([generationTask,result,evaluation,state.graph.version]);if(stamp===generationResultStamp)return;generationResultStamp=stamp;
  if(generationCy){generationCy.destroy();generationCy=null;}
  if(result){
    const scope=result.context?.scope;
    const title=result.task_type&&result.task_type!=='qa'?`${generationTasks[result.task_type]?.label||'论文生成'} · ${result.paper_ids?.length||scope?.requested_paper_ids?.length||0} 篇论文`:result.question;
    $('#generation-output').innerHTML=`<div class="card"><span class="micro">${escapeHTML(generationTasks[result.task_type||'qa']?.label||'问题回答')} · 图谱 ${escapeHTML(result.graph_version||'未建立')}</span><h2>${escapeHTML(title)}</h2>${staleNotice(result)}${scope?`<p class="muted">实际涉及 ${scope.paper_count} 篇论文 · 使用 ${scope.selected_facts}/${scope.candidate_facts} 条候选事实 · 范围：${escapeHTML(scope.requested_paper_ids.join('、')||'空')}</p>${scope.truncated?'<p class="notice">检索已截断至 300 条事实，当前结果仅覆盖部分材料。</p>':''}`:''}${generationAnswerHTML(result)}<details id="generation-subgraph"><summary>查看本次检索子图</summary><div id="generation-graph"></div>${jsonDetails(result.context,'查看检索明细与证据')}</details></div>`;
    $('#generation-subgraph').ontoggle=()=>{if($('#generation-subgraph').open&&window.cytoscape){if(!generationCy)generationCy=createGraph('generation-graph',result.context,false);setTimeout(()=>{generationCy?.resize();generationCy?.fit(undefined,25);},30);}};
  }else $('#generation-output').innerHTML=empty(`尚无${generationTasks[generationTask].label}结果。${generationTask==='qa'?'选择问题模板和实体或自行提问，再生成回答。':'选择论文后点击生成。'}`);
  $('#generation-output').onclick=event=>{const link=event.target.closest('[data-claim-link]');if(link){event.preventDefault();document.getElementById(link.dataset.claimLink)?.scrollIntoView({behavior:'smooth',block:'center'});}};
  const metrics=evaluation?.metrics;
  $('#generation-eval-output').innerHTML=evaluation?`<h3>生成评测 · ${evaluation.cases.length} 道题</h3>${staleNotice(evaluation)}<p class="muted">已审核 ${metrics?.reviewed??0}/${evaluation.cases.length} 道。评分范围 1–5；未审核显示 —。</p>${metrics?generationMetricsHTML(metrics):''}${jsonDetails(evaluation,'查看逐例结果与对照')}`:'';
}
function generationMetricsHTML(metrics){
  const rows=Object.entries(metrics.by_task||{all:metrics});
  return `<div class="generation-metrics"><table><thead><tr><th>任务</th><th>已审核</th><th>正确率</th><th>引用准确率</th><th>证据支持率</th><th>要点覆盖率</th><th>正确拒答率</th><th>相关性</th><th>组织</th><th>综合</th><th>比较</th><th>建议</th></tr></thead><tbody>${rows.map(([kind,m])=>`<tr><td>${escapeHTML(generationTasks[kind]?.label||'全部')}</td><td>${m.reviewed}/${m.total}</td>${['accuracy','citation_accuracy','evidence_coverage','key_point_coverage','abstention_accuracy',...Object.keys(generationScoreLabels)].map(k=>`<td>${m[k]==null?'—':Number(m[k]).toFixed(3)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${metrics.baseline?`<details><summary>无图谱对照指标（相同人工量表）</summary>${generationMetricsHTML(metrics.baseline)}</details>`:''}`;
}
function generationOpenForm(title,help,html,save){
  $('#editor-title').textContent=title;$('#editor-help').textContent=help;$('#editor-json').hidden=true;$('#editor-fields').innerHTML=html;$('#editor-error').textContent='';editorSave=save;$('#editor-dialog').showModal();
}
function generationMultiOptions(kind,selected=[]){
  const rows=kind==='entities'?state.graph.nodes.map(n=>[n.id,n.name]):state.papers.filter(p=>(state.graph.paper_ids||[]).includes(p.paper_id)).map(p=>[p.paper_id,p.title]);
  const known=new Set(rows.map(([id])=>id));for(const id of selected)if(!known.has(id))rows.push([id,id+'（已失效，需核对）']);
  return rows.map(([id,label])=>`<option value="${escapeHTML(id)}" ${selected.includes(id)?'selected':''}>${escapeHTML(label)}</option>`).join('');
}
async function editGenerationQuestions(){
  try{
    const original=await api('/api/questions');let rows=original.map(q=>({...q}));
    const card=(q,i)=>`<fieldset class="generation-question-row" data-index="${i}"><legend>评测题 ${i+1}</legend><label>题目 ID<input data-field="id" value="${escapeHTML(q.id||'')}"></label><label>任务<select data-field="task_type">${Object.entries(generationTasks).map(([k,v])=>`<option value="${k}" ${(q.task_type||'qa')===k?'selected':''}>${v.label}</option>`).join('')}</select></label><label>问题（仅问题回答必填）<textarea data-field="question">${escapeHTML(q.question||'')}</textarea></label><label>实体锚点（仅问题回答，可多选）<select multiple data-field="entity_ids">${generationMultiOptions('entities',q.entity_ids)}</select></label><label>论文范围（总结/综述必选）<select multiple data-field="paper_ids">${generationMultiOptions('papers',q.paper_ids)}</select></label><label>参考事实 ID（每行一条）<textarea data-field="expected_fact_ids">${escapeHTML((q.expected_fact_ids||[]).join('\n'))}</textarea></label><label>参考要点（每行一条）<textarea data-field="reference_points">${escapeHTML((q.reference_points||[]).join('\n'))}</textarea></label><label>预期证据不足<select data-field="should_abstain"><option value="">未指定</option><option value="true" ${q.should_abstain===true?'selected':''}>应拒答</option><option value="false" ${q.should_abstain===false?'selected':''}>应有支撑结论</option></select></label><label>分类<input data-field="category" value="${escapeHTML(q.category||'')}"></label>${q.needs_review?'<p class="notice">引用已变化，请先核对所有参考内容，再取消下方待核对标记。</p><label><input type="checkbox" data-field="needs_review" checked> 待核对</label>':''}<button type="button" data-remove-question>移除此题</button></fieldset>`;
    generationOpenForm('维护三类任务评测题','使用真实实体和人工确认的参考要点；多选框可使用 Ctrl / Command 多选。',`<div id="generation-question-rows">${rows.map(card).join('')}</div><button type="button" id="generation-add-question">新增题目</button>`,async()=>{
      const value=$$('.generation-question-row').map(el=>{const q={...(rows[Number(el.dataset.index)]||{})};el.querySelectorAll('[data-field]').forEach(input=>{const k=input.dataset.field;q[k]=input.multiple?[...input.selectedOptions].map(o=>o.value):['expected_fact_ids','reference_points'].includes(k)?input.value.split('\n').map(v=>v.trim()).filter(Boolean):k==='should_abstain'?(input.value===''?null:input.value==='true'):k==='needs_review'?input.checked:input.value;});return q;});
      await api('/api/questions',{method:'PUT',body:JSON.stringify(value)});notify('评测题已保存');
    });
    $('#generation-question-rows').onclick=event=>{if(event.target.matches('[data-remove-question]'))event.target.closest('fieldset').remove();};
    $('#generation-add-question').onclick=()=>{const i=rows.length;rows.push({});$('#generation-question-rows').insertAdjacentHTML('beforeend',card({},i));};
  }catch(error){notify(error.message);}
}
function generationReviewFields(manual,kind){
  const bool=(key,label)=>`<label>${label}<select data-score="${key}"><option value="">未审核</option><option value="true" ${manual[key]===true?'selected':''}>是</option><option value="false" ${manual[key]===false?'selected':''}>否</option></select></label>`;
  const scores=kind==='qa'?[]:kind==='summary'?['relevance','organization','synthesis']:Object.keys(generationScoreLabels);
  return `${bool('correct','整体内容正确')}${bool('abstention_correct','证据不足题是否正确拒答')}${Object.entries(generationCountLabels).map(([key,label])=>`<label>${label}<input data-score="${key}" type="number" min="0" step="1" value="${escapeHTML(manual[key]??'')}"></label>`).join('')}${scores.map(key=>`<label>${generationScoreLabels[key]}<select data-score="${key}"><option value="">未评分</option>${[1,2,3,4,5].map(v=>`<option value="${v}" ${manual[key]===v?'selected':''}>${v}</option>`).join('')}</select></label>`).join('')}<label>备注<textarea data-score="note">${escapeHTML(manual.note||'')}</textarea></label>`;
}
function reviewGeneration(){
  const evaluation=state.results.generation_evaluation;if(!evaluation)return notify('请先运行生成评测');
  if(isStatic)return notify('静态结果只读，请在实时服务填写评价。');
  const value=structuredClone(evaluation);
  // 按题目哈希固定打乱 A/B，评分表不揭示实验分组；两个输出使用同一量表。
  const cards=value.cases.map((c,i)=>{
    const reverse=[...c.question_id].reduce((n,ch)=>n+ch.charCodeAt(0),0)%2===1;
    const variants=reverse?['baseline_manual','manual']:['manual','baseline_manual'];
    return `<fieldset class="generation-review-case"><legend>${escapeHTML(c.question_id)} · ${escapeHTML(generationTasks[c.task_type||'qa'].label)}</legend><h3>${escapeHTML(c.question)}</h3><p>参考要点：${escapeHTML((c.reference_points||[]).join('；')||'未设置')}</p><p>参考事实：${escapeHTML((c.expected_fact_ids||[]).join('、')||'未设置')} · 预期拒答：${c.should_abstain==null?'未指定':c.should_abstain?'是':'否'}</p>${variants.map((key,j)=>`<details open><summary>输出 ${j?'B':'A'}</summary><div class="generation-review-output">${key==='manual'?generationAnswerHTML(c.with_graph,`review-${i}-${j}`):`<p class="generation-baseline">${escapeHTML(c.without_graph?.answer||JSON.stringify(c.without_graph))}</p>`}</div><div class="generation-review-fields" data-case="${i}" data-manual="${key}">${generationReviewFields(c[key]||{},c.task_type||'qa')}</div></details>`).join('')}</fieldset>`;
  }).join('');
  generationOpenForm('人工评价 · 匿名 A/B 对照','同一量表评价两个输出。1=严重偏题或错误，2=较多缺漏，3=基本可用但需修订，4=准确完整且有少量不足，5=准确、完整、清晰。事实支持需核对原文；研究建议评价依据、推理及可验证性。未审核请留空。',cards,async()=>{
    $$('.generation-review-fields').forEach(el=>{const c=value.cases[Number(el.dataset.case)],key=el.dataset.manual;c[key]={...(c[key]||{})};el.querySelectorAll('[data-score]').forEach(input=>{const field=input.dataset.score;c[key][field]=field==='note'?input.value:input.value===''?null:['correct','abstention_correct'].includes(field)?input.value==='true':Number(input.value);});});
    await api('/api/generation-review',{method:'PUT',body:JSON.stringify(value)});await refresh();notify('人工评价已保存');
  });
}
