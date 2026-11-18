/* 缺失关系工作区：结果来自版本化预测产物，不从任务列表猜测输出。 */
'use strict';
const relationLabels = {USES_COMPONENT:'使用组件',SOLVES:'解决任务',OUTPUTS:'输出表示',TRAINED_ON:'训练数据集',EVALUATED_ON:'评测数据集',USES_METRIC:'使用指标'};
const relationSourceTypes = {USES_COMPONENT:['Method'],SOLVES:['Paper','Method'],OUTPUTS:['Method'],TRAINED_ON:['Method'],EVALUATED_ON:['Paper','Method'],USES_METRIC:['Paper','Method']};
let relationPage=1, relationSelection=null, relationSignature='', relationSourceSignature='', relationSubmitting=false, relationCy=null;
const relationKey = c => JSON.stringify([c.source_id,c.relation,c.target_id]);
const relationResult = () => state.results?.relation_prediction;
const relationNode = id => relationResult()?.context?.nodes.find(n=>n.id===id) || state.graph.nodes.find(n=>n.id===id) || {id,name:id};
const relationSelectedTypes = () => [...document.querySelectorAll('#relation-types input:checked')].map(el=>el.value);

function initRelationPrediction() {
  $('#relation-types').innerHTML=Object.entries(relationLabels).map(([id,label])=>`<label><input type="checkbox" value="${id}" checked>${label}</label>`).join('');
  $('#relation-result-type').innerHTML='<option value="">全部关系</option>'+Object.entries(relationLabels).map(([id,label])=>`<option value="${id}">${label}</option>`).join('');
  $('#relation-mode').onchange=()=>{updateRelationSources();renderRelationWorkspace();};
  $('#relation-source-search').oninput=()=>updateRelationSources(true);
  $('#relation-types').onchange=()=>{updateRelationSources(true);renderRelationWorkspace();};
  for(const selector of ['#relation-result-search','#relation-result-type'])$(selector).addEventListener('input',()=>{relationPage=1;renderRelationRows();});
  $('#relation-run').onclick=async()=>{
    if(relationSubmitting)return;
    const relations=relationSelectedTypes();
    const source=$('#relation-mode').value==='single'?$('#relation-source').value:null;
    if(!relations.length)return notify('请至少选择一种关系类型');
    if($('#relation-mode').value==='single'&&!source)return notify('请选择源实体');
    relationSubmitting=true;renderRelationWorkspace();
    try {await api('/api/run',{method:'POST',body:JSON.stringify({stage:'relation_predict',source_id:source,relation_types:relations})});await refresh();}
    catch(error){notify(error.message);$('#relation-job').textContent=error.message;}
    finally{relationSubmitting=false;renderRelationWorkspace();}
  };
}
function updateRelationSources(force=false) {
  const single=$('#relation-mode').value==='single';$('#relation-source-label').hidden=!single;
  const signature=JSON.stringify([state.graph.version,relationSelectedTypes(),$('#relation-source-search').value]);
  if(!force&&signature===relationSourceSignature)return;
  relationSourceSignature=signature;
  const old=$('#relation-source').value,query=$('#relation-source-search').value.trim().toLowerCase();
  const types=new Set(relationSelectedTypes().flatMap(r=>relationSourceTypes[r]));
  const nodes=state.graph.nodes.filter(n=>types.has(n.type)&&n.name.toLowerCase().includes(query));
  $('#relation-source').innerHTML='<option value="">选择源实体</option>'+nodes.map(n=>`<option value="${escapeHTML(n.id)}">${escapeHTML(n.name)} · ${n.type==='Paper'?'论文':'方法'}</option>`).join('');
  if(nodes.some(n=>n.id===old))$('#relation-source').value=old;
}
function renderRelationWorkspace() {
  updateRelationSources();
  const result=relationResult(),jobs=state.jobs||[];
  const active=jobs.find(j=>['queued','running'].includes(j.status));
  const latest=jobs.find(j=>j.kind==='relation_predict');
  const allowedTypes=new Set(relationSelectedTypes().flatMap(r=>relationSourceTypes[r]));
  const eligible=state.graph.nodes.filter(n=>allowedTypes.has(n.type)).length;
  $('#relation-stats').innerHTML=[['图谱版本',state.graph.version?.slice(0,10)||'未建立'],['可预测实体',eligible],['候选关系',result?.statistics.candidate_count??'—'],['最近成功预测',result?new Date(result.time).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'尚未运行']].map(([label,value])=>`<div class="stat"><div class="stat-label">${label}</div><div class="relation-stat-value">${escapeHTML(value)}</div></div>`).join('');
  const button=$('#relation-run');button.disabled=isStatic||relationSubmitting||!!active||!state.graph.edges.length||!eligible;
  button.textContent=relationSubmitting?'正在提交…':active?.kind==='relation_predict'?'正在预测…':'开始预测 ↗';
  $('#prediction-advanced').querySelectorAll('button').forEach(b=>b.disabled=isStatic||!!active);
  $('#relation-source').disabled=isStatic;
  $('#relation-job').innerHTML=isStatic?'<p class="micro">静态展示只读，可筛选已导出的预测结果。</p>':latest&&['queued','running'].includes(latest.status)?`<p>正在${latest.status==='queued'?'排队':'扫描图谱'}… ${escapeHTML(latest.logs?.at(-1)?.message||'')}</p>${latest.total?`<progress value="${latest.completed}" max="${latest.total}"></progress>`:''}`:latest&&['failed','interrupted'].includes(latest.status)?`<p class="error">${escapeHTML(latest.error||'预测已中断，请重新运行。')}</p>`:active?'<p class="micro">其他后台任务正在运行，请等待完成后预测。</p>':'';
  const stale=result&&result.graph_version!==state.graph.version;
  $('#relation-version-notice').innerHTML=stale?'<p class="notice">此预测来自旧图谱版本，路径与证据按当时快照展示。请重新预测以获取当前候选。</p>':'';
  const signature=JSON.stringify([result?.time,result?.graph_version,state.graph.version]);
  if(signature!==relationSignature){relationSignature=signature;relationPage=1;relationSelection=null;renderRelationRows();renderRelationDetail();}
  if(relationCy&&location.hash==='#prediction')requestAnimationFrame(()=>{relationCy?.resize();relationCy?.fit(undefined,25);});
}
function renderRelationRows() {
  const result=relationResult(),query=$('#relation-result-search').value.trim().toLowerCase(),type=$('#relation-result-type').value;
  const rows=(result?.candidates||[]).filter(c=>(!type||c.relation===type)&&(!query||[relationNode(c.source_id).name,relationNode(c.target_id).name].some(n=>n.toLowerCase().includes(query))));
  const pages=Math.max(1,Math.ceil(rows.length/20));relationPage=Math.min(relationPage,pages);
  $('#relation-result-count').textContent=result?`${rows.length} / ${result.candidates.length} 条 · ${result.scope.source_id?'单实体':'全图'}预测`:'';
  if(!result||!rows.length){$('#relation-results').innerHTML=empty(!state.graph.edges.length?'尚无正式图谱，请先审核并导入图谱。':!result?'设置预测范围，开始发现缺失的关系。':!result.candidates.length?'未发现有路径支持的新关系，可尝试其他实体或补充图谱。':'没有匹配的候选，请调整筛选条件。');$('#relation-pagination').innerHTML='';return;}
  $('#relation-results').innerHTML=`<table class="relation-table"><thead><tr><th>源实体 → 预测关系 → 目标实体</th><th>路径分数</th><th>路径数</th><th>依据</th></tr></thead><tbody>${rows.slice((relationPage-1)*20,relationPage*20).map(c=>`<tr class="${relationKey(c)===relationSelection?'relation-selected':''}"><td><strong>${escapeHTML(relationNode(c.source_id).name)}</strong><span class="relation-arrow">→ ${relationLabels[c.relation]} →</span><strong>${escapeHTML(relationNode(c.target_id).name)}</strong><small>待核验</small></td><td>${c.score.toFixed(1)}</td><td>${c.path_count}</td><td><button data-relation-key="${escapeHTML(relationKey(c))}" aria-label="查看 ${escapeHTML(relationNode(c.source_id).name)} 到 ${escapeHTML(relationNode(c.target_id).name)} 的预测依据">查看</button></td></tr>`).join('')}</tbody></table>`;
  $('#relation-results').querySelectorAll('[data-relation-key]').forEach(b=>b.onclick=()=>{relationSelection=b.dataset.relationKey;renderRelationRows();renderRelationDetail();if(matchMedia('(max-width:1250px)').matches)$('#relation-detail').scrollIntoView({behavior:'smooth',block:'start'});});
  $('#relation-pagination').innerHTML=`<button id="relation-prev" ${relationPage===1?'disabled':''}>上一页</button><span class="micro">${relationPage} / ${pages}</span><button id="relation-next" ${relationPage===pages?'disabled':''}>下一页</button>`;
  $('#relation-prev').onclick=()=>{relationPage--;renderRelationRows();};$('#relation-next').onclick=()=>{relationPage++;renderRelationRows();};
}
function renderRelationDetail() {
  relationCy?.destroy();relationCy=null;
  const result=relationResult(),candidate=result?.candidates.find(c=>relationKey(c)===relationSelection),panel=$('#relation-detail');
  if(!candidate){panel.innerHTML='<h2>预测依据</h2>'+empty('选择一条候选关系，查看路径与原文线索。');return;}
  const context=result.context,edges=new Map(context.edges.map(e=>[e.id,e])),evidence=new Map(context.evidence.map(e=>[e.id,e]));
  const stale=result.graph_version!==state.graph.version;
  panel.innerHTML=`<div class="card-heading"><h2>预测依据</h2><span class="pill">待核验</span></div><h3>${escapeHTML(relationNode(candidate.source_id).name)} → ${relationLabels[candidate.relation]} → ${escapeHTML(relationNode(candidate.target_id).name)}</h3><p class="micro">路径分数 ${candidate.score.toFixed(1)} · ${candidate.path_count} 条支持路径 · 展示前 ${candidate.paths.length} 条</p><div id="relation-path-graph" aria-label="已有关系实线、预测关系虚线的路径子图"></div><p class="micro">实线：已有关系 · 蓝色虚线：预测关系</p>${candidate.paths.map((path,i)=>`<details class="relation-path" ${i===0?'open':''}><summary>路径 ${i+1} · ${path.node_ids.length-1} 跳</summary><p>${path.node_ids.map(n=>escapeHTML(relationNode(n).name)).join(' ↔ ')}</p>${path.steps.map(ids=>ids.map(id=>{const edge=edges.get(id);return edge?`<p class="micro">${escapeHTML(relationNode(edge.source).name)} → ${relationLabels[edge.relation]||escapeHTML(edge.relation)} → ${escapeHTML(relationNode(edge.target).name)}</p>`:'';}).join('')).join('')}${path.evidence_ids.length?path.evidence_ids.map(id=>{const e=evidence.get(id);if(!e)return '<p class="micro">该证据未包含在快照中。</p>';const liveEvidence=state.graph.evidence?.find(current=>current.id===id);const linkable=!isStatic&&(!stale||(liveEvidence&&e.pdf_sha256&&liveEvidence.pdf_sha256===e.pdf_sha256&&liveEvidence.paper_id===e.paper_id));return `<div class="evidence-record"><strong>${escapeHTML(e.paper_id)} · PDF 第 ${e.page} 页</strong><blockquote>${escapeHTML(e.quote)}</blockquote>${linkable?`<a href="/api/pdf/${encodeURIComponent(e.paper_id)}#page=${Number(e.page)}" target="_blank" rel="noopener">查看原 PDF ↗</a>`:''}</div>`;}).join(''):'<p class="micro">该路径暂无原文证据。</p>'}</details>`).join('')}<p class="micro">以上原文支持路径中的已有关系，不能直接证明预测关系成立。</p>`;
  if(!window.cytoscape)return;
  const nodeIds=new Set(candidate.paths.flatMap(p=>p.node_ids)),edgeIds=new Set(candidate.paths.flatMap(p=>p.edge_ids));
  relationCy=cytoscape({container:$('#relation-path-graph'),elements:[...context.nodes.filter(n=>nodeIds.has(n.id)).map(n=>({data:{id:n.id,label:n.name,color:colors[n.type]||'#8994aa'}})),...context.edges.filter(e=>edgeIds.has(e.id)).map(e=>({data:{...e,label:relationLabels[e.relation]||e.relation}})),{data:{id:'relation-predicted-edge',source:candidate.source_id,target:candidate.target_id,label:relationLabels[candidate.relation]},classes:'predicted'}],style:[{selector:'node',style:{'background-color':'data(color)',label:'data(label)','font-size':10,'text-wrap':'ellipsis','text-max-width':100,'text-valign':'bottom','text-margin-y':6,width:20,height:20}},{selector:'edge',style:{width:1.5,'line-color':'#bdc7d8','target-arrow-color':'#bdc7d8','target-arrow-shape':'triangle','curve-style':'bezier',label:'','font-size':8,'text-background-color':'white','text-background-opacity':.9}},{selector:'.predicted',style:{'line-style':'dashed','line-color':'#315df4','target-arrow-color':'#315df4',label:'data(label)',width:2.5}}],layout:{name:'cose',animate:false,padding:25,idealEdgeLength:95,nodeRepulsion:6500},minZoom:.2,maxZoom:2});
}
