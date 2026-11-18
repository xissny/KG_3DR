/* 页面只负责交互；算法统一由后端调用 src 中的模块。 */
'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const isStatic = !!window.KG_STATIC || location.protocol === 'file:';
const colors = {Paper:'#315df4', Method:'#17a591', Component:'#9271d9', Task:'#e59b42', Representation:'#4e9bd7', Dataset:'#dd728c', Metric:'#8a9caf'};
const names = {overview:'项目概览', papers:'论文管理', graph:'知识抽取与图谱', classification:'论文分类', prediction:'关系预测', generation:'证据问答'};
const stageNames = {relation_predict:'缺失关系预测',entity_resolution:'AI 实体同义检测',papers:'生成论文清单',parse:'解析正文',extract:'DeepSeek 抽取',pipeline:'解析与抽取',validate:'校验事实',import:'导入 Neo4j',automatic_classification:'图谱自动分类',classification_taxonomy:'更新分类类别',classification:'分类评测',classify:'单篇分类',prediction:'关系补全评测',predict:'缺失组件预测',ask:'证据问答',generation_eval:'生成评测',export:'导出 Demo',materials:'生成报告与 PPT'};
let state = {papers:[], graph:{nodes:[],edges:[],evidence:[]}, results:{}, jobs:[]};
let candidates = [], candidateGroups = [], displayedGraph = state.graph, cy = null, miniCy = null, editorSave = null, previousJobStatus = '';
let graphMode = 'official', graphNeedsRefresh = true, fullGraph = null;
let reviewStatus = 'pending', visibleReviewGroups = [];
let clearingJobHistory = false, stateRequestVersion = 0, polling = false;
let miniGraphVersion = null;
let labelReview = null, candidatesLoaded = false;
const labelDirty = new Set();
const graphSelections = {}; // 正式/候选共用论文选择，教学数据单独记录，防止同名ID串用。
const notify = (message) => { $('#toast').textContent = message; $('#toast').style.display='block'; clearTimeout(notify.timer); notify.timer=setTimeout(()=>$('#toast').style.display='none',5000); };

async function api(path, options={}) {
  if (isStatic) throw new Error('当前为静态展示。请启动服务器服务后执行该操作。');
  const headers = {...options.headers};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json';
  const response = await fetch(path, {...options, headers});
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail==='string' ? payload.detail : JSON.stringify(payload.detail));
  return payload;
}
function empty(text) { return `<div class="empty">${escapeHTML(text)}</div>`; }
function jsonDetails(value, title='查看完整输出') { return `<details><summary>${escapeHTML(title)}</summary><pre class="result-json">${escapeHTML(JSON.stringify(value,null,2))}</pre></details>`; }
function metric(label,value) { return `<div class="metric"><strong>${value==null?'—':typeof value==='number'?value.toFixed(3):escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></div>`; }
function staleNotice(result) { return result?.graph_version && result.graph_version!==state.graph.version ? '<p class="notice">此结果来自旧图谱版本，请重新运行评测。</p>' : ''; }
function nodeName(id) { return state.graph.nodes.find(n=>n.id===id)?.name || id; }

function navigate() {
  const page = location.hash.slice(1) || 'overview';
  const selected = names[page] ? page : 'overview';
  $$('.page').forEach(el=>el.classList.toggle('active',el.id===selected));
  $$('nav a').forEach(el=>el.classList.toggle('active',el.dataset.page===selected));
  $('#breadcrumb').textContent=names[selected];
  if (selected==='overview') setTimeout(renderMiniGraph,30);
  if(selected==='prediction')renderRelationWorkspace();
  if(selected==='classification')loadAutomaticClassification().catch(error=>notify(error.message));
  if (selected==='graph') {
    loadEntityResolution().catch(error=>notify(error.message));
    if(!isStatic && !candidatesLoaded)loadCandidates().catch(error=>notify(error.message));
    if (graphNeedsRefresh && graphMode==='official') loadOfficialGraph();
    else setTimeout(()=>{cy?.resize();cy?.fit(undefined,35);},30);
  }
}
window.addEventListener('hashchange',navigate);

async function refresh() {
  const requestVersion=++stateRequestVersion;
  try {
    const nextState = isStatic ? window.KG_STATIC || state : await api('/api/state'+(state.revision?'?revision='+encodeURIComponent(state.revision):''));
    if(nextState.unchanged)return;
    if(requestVersion!==stateRequestVersion)return; // 丢弃晚到的旧轮询，防止清除后旧记录重新出现。
    const renumbered = state.papers.length > 0 && state.paper_numbering_revision !== nextState.paper_numbering_revision;
    state = nextState;
    if(renumbered){labelReview=null;labelDirty.clear();resetAutomaticSelection();}
    if(renumbered) {
      generationEntities.clear();generationPapers.clear();generationTemplateEntityIds=[];generationOptionsStamp='';updateGenerationTemplateQuestion();
      for(const selector of ['#extract-paper','#classify-paper','#review-paper'])$(selector).value='';
      delete graphSelections.research;
      if(graphMode!=='teaching'){fullGraph=null;graphNeedsRefresh=true;}
      $('#classify-single').innerHTML='';$('#predict-single').innerHTML='';
    }
    renderState();
    if(renumbered && !isStatic) {
      await loadCandidates();
      if(graphMode!=='teaching' && location.hash==='#graph')await loadOfficialGraph();
      notify('论文编号已更新，请按新编号选择论文。');
    }
    const stamp=state.jobs.map(j=>`${j.id}:${j.status}`).join('|');
    if (previousJobStatus && stamp!==previousJobStatus) {
      const completed = state.jobs.find(j=>j.status==='complete');
      if (completed) {
        if (['pipeline','extract'].includes(completed.kind)) await loadCandidates();
        if (completed.kind==='pipeline') showCandidateGraph();
        if (completed.kind==='import') { graphNeedsRefresh=true; if(location.hash==='#graph') await loadOfficialGraph(); }
        if (completed.kind==='classify') renderSingleClassification(completed.result);
        if (completed.kind==='predict') renderSinglePrediction(completed.result);
      }
    }
    previousJobStatus=stamp;
  } catch(error) { if(requestVersion!==stateRequestVersion)return; $('#connection').textContent='服务未连接'; notify(error.message); }
}
function renderState() {
  $('#nav-paper-count').textContent=state.papers.length;
  const included=state.included_count ?? state.papers.filter(p=>p.included!==false).length;
  const stats=[['纳入论文',included,'正式提交要求 ≥ 20 篇'],['知识实体',state.graph.nodes.length,'论文 · 方法 · 组件 · 任务'],['已核验关系',state.graph.edges.length,'每条关系均可追溯证据'],['待审核证据',state.pending_evidence_count ?? Math.max(0,(state.candidate_count||0)-(state.approved_count||0)),'先核验，再进入正式图谱']];
  $('#stats').innerHTML=stats.map(([label,value,caption])=>`<div class="stat"><div class="stat-label">${label}<span>↗</span></div><div class="stat-value">${value}</div><div class="stat-caption">${caption}</div></div>`).join('');
  $('#corpus-notice').textContent=included<20?`当前纳入 ${included} 篇；可调试运行，正式提交还需 ${20-included} 篇。元数据中的创建年份不一定是发表年份。`:`当前纳入 ${included} 篇。请检查筛选依据、版本合并和元数据。`;
  $('#papers-body').innerHTML=state.papers.map(p=>`<tr><td><strong>${escapeHTML(p.paper_id)}</strong></td><td>${escapeHTML(p.title)}<small>${escapeHTML(p.pdf_file?.split('/').pop()||'')}</small></td><td>${escapeHTML(p.year||'待核对')}</td><td><span class="pill ${p.parse_status==='needs_ocr'?'warning':''}">${escapeHTML(p.parse_status||p.status)}</span></td><td>${p.included!==false?'是':'否'}</td><td><button data-edit-paper="${escapeHTML(p.paper_id)}">编辑</button> <button class="danger" data-delete-paper="${escapeHTML(p.paper_id)}">删除</button></td></tr>`).join('')||`<tr><td colspan="6">${empty('尚无论文。先选择 PDF 上传，再生成论文清单。')}</td></tr>`;
  for (const id of ['extract-paper','classify-paper']) {
    const select=$('#'+id), old=select.value;
    select.innerHTML=(id==='extract-paper'?'<option value="">全部纳入论文</option>':'<option value="">选择论文</option>')+state.papers.filter(p=>p.included!==false).map(p=>`<option value="${escapeHTML(p.paper_id)}">${escapeHTML(p.paper_id+' · '+p.title)}</option>`).join('');
    select.value=old;
  }
  const oldMethod=$('#predict-method').value;
  $('#predict-method').innerHTML='<option value="">选择方法</option>'+state.graph.nodes.filter(n=>n.type==='Method').map(n=>`<option value="${escapeHTML(n.id)}">${escapeHTML(n.name)}</option>`).join('');
  $('#predict-method').value=oldMethod;
  if(document.activeElement!==$('#aliases-editor')) $('#aliases-editor').value=JSON.stringify(state.aliases||{},null,2);
  $('#version-footer').textContent=state.graph.version?`GRAPH ${state.graph.version.slice(0,12)}${state.exported_at?' · 静态快照':''}`:'等待正式论文与核验数据';
  renderReviewPaperOptions();
  if(location.hash==='#graph')loadEntityResolution().catch(error=>notify(error.message));
  renderClassification();renderPrediction();renderGeneration();renderJobs();renderMiniGraph();
  if(location.hash==='#classification')loadAutomaticClassification().catch(error=>notify(error.message));
}
function renderMiniGraph() {
  if(!$('#overview').classList.contains('active'))return;
  const version=state.graph.version || JSON.stringify([state.graph.nodes,state.graph.edges]);
  if(miniCy && miniGraphVersion===version){miniCy.resize();return;}
  miniGraphVersion=version;
  if(miniCy) miniCy.destroy();
  const graph=state.graph;
  if(!window.cytoscape || !graph.edges.length) {
    $('#mini-graph').innerHTML=empty('正式图谱尚未建立。可从侧栏打开独立教学图谱。');
    return;
  }
  miniCy=createGraph('mini-graph',graph,false);
}
function createGraph(container,graph,interactive=true) {
  const nodeIds=new Set(graph.nodes.map(n=>n.id));
  const edges=graph.edges.filter(e=>nodeIds.has(e.source)&&nodeIds.has(e.target));
  const instance=cytoscape({container:$('#'+container), elements:[...graph.nodes.map(n=>({data:{...n,label:n.name,color:colors[n.type]||'#8494ad'}})),...edges.map(e=>({data:{...e,label:e.relation}}))],
    style:[{selector:'node',style:{'background-color':'data(color)','label':interactive?'data(label)':'data(label)','font-size':interactive?10:8,'color':'#56647b','text-valign':'bottom','text-margin-y':7,'width':interactive?24:17,'height':interactive?24:17,'text-max-width':110,'text-wrap':'ellipsis','border-width':4,'border-color':'#ffffff','overlay-opacity':0}},
      {selector:'edge',style:{'width':1.1,'line-color':'#d0d9eb','target-arrow-color':'#a6b6d0','target-arrow-shape':interactive?'triangle':'none','curve-style':'bezier','label':'','font-size':7,'color':'#8994a9','text-background-color':'#fff','text-background-opacity':0.85,'text-rotation':'autorotate'}},
      {selector:':selected',style:{'border-width':5,'border-color':'#b8c8ff','line-color':'#315df4','target-arrow-color':'#315df4'}},
      {selector:'edge:selected',style:{label:'data(label)',width:2}},
      {selector:'.dim',style:{opacity:0.12}},{selector:'.hidden',style:{display:'none'}}],
    layout:{name:'cose',animate:false,padding:35,idealEdgeLength:95,nodeRepulsion:6500},minZoom:.15,maxZoom:3,wheelSensitivity:.2});
  if(interactive) {
    instance.on('tap','node',event=>showNode(event.target.data()));
    instance.on('tap','edge',event=>showEdge(event.target.data()));
    instance.on('dbltap','node',event=>{instance.elements().addClass('dim');event.target.closedNeighborhood().removeClass('dim');instance.fit(event.target.closedNeighborhood(),50);});
  }
  return instance;
}
function graphSelectionScope() { return graphMode === 'teaching' ? 'teaching' : 'research'; }

function graphSelection() {
  const scope=graphSelectionScope();
  const revision=scope==='teaching'?'teaching':(state.paper_numbering_revision||'legacy');
  if(graphSelections[scope] && (graphSelections[scope].revision||'legacy')!==revision)delete graphSelections[scope];
  if (!graphSelections[scope]) {
    let stored=null;
    try { stored=JSON.parse(localStorage.getItem('kg3dr.graph.papers.'+scope)); } catch (_) {}
    graphSelections[scope]=stored && (stored.revision||'legacy')===revision && ['all','subset'].includes(stored.mode) && Array.isArray(stored.paper_ids)
      ? {...stored,revision} : {mode:'all',paper_ids:[],revision};
  }
  return graphSelections[scope];
}

function graphPaperOptions() {
  const graph=fullGraph || {nodes:[],edges:[],evidence:[]};
  const papers=graphMode==='teaching' ? [] : state.papers;
  const titles=new Map(papers.map(p=>[p.paper_id,p.title]));
  (graph.nodes || []).filter(n=>n.type==='Paper').forEach(n=>{if(!titles.has(n.id))titles.set(n.id,n.name);});
  const evidenceById=new Map((graph.evidence || []).map(e=>[e.id,e]));
  const ids=new Set([...(graph.paper_ids || []),...papers.map(p=>p.paper_id),
    ...(graph.evidence || []).map(e=>e.paper_id)]);
  const counts=new Map();
  (graph.edges || []).forEach(edge=>{
    const sources=new Set([...(edge.paper_ids || []),...(edge.evidence_ids || []).flatMap(id=>{
      const row=evidenceById.get(id);return row?[row.paper_id]:[];
    })]);
    sources.forEach(id=>{ids.add(id);counts.set(id,(counts.get(id)||0)+1);});
  });
  return [...ids].sort().map(id=>({id,title:titles.get(id)||id,count:counts.get(id)||0}));
}

function selectedGraphPapers() {
  const selection=graphSelection();
  return graphPaperOptions().filter(p=>selection.mode==='all'||selection.paper_ids.includes(p.id)).map(p=>p.id);
}

function renderGraphPaperOptions() {
  const options=graphPaperOptions(), selected=new Set(selectedGraphPapers());
  $('#graph-paper-options').innerHTML=options.map(p=>`<label class="paper-checkbox"><input type="checkbox" class="graph-paper-check" value="${escapeHTML(p.id)}" ${selected.has(p.id)?'checked':''}><span><strong>${escapeHTML(p.id)}</strong> · ${escapeHTML(p.title)}<small>${p.count} 条关系来源</small></span></label>`).join('') || '<p class="muted">当前尚无可选论文。</p>';
}

function changeGraphPapers(paperIds,all=false) {
  const scope=graphSelectionScope();
  graphSelections[scope]={mode:all?'all':'subset',paper_ids:paperIds,revision:scope==='teaching'?'teaching':(state.paper_numbering_revision||'legacy')};
  try {localStorage.setItem('kg3dr.graph.papers.'+scope,JSON.stringify(graphSelections[scope]));} catch (_) {}
  if(fullGraph)setGraph(fullGraph,graphMode);
}

function selectedGraph() {
  return KGFilters.filterGraphByPapers(fullGraph || {nodes:[],edges:[],evidence:[]},selectedGraphPapers());
}

function setGraph(graph,mode,local=false) {
  if(!local)fullGraph=graph;
  graphMode=mode;
  renderGraphPaperOptions();
  graph=KGFilters.filterGraphByPapers(graph,selectedGraphPapers());
  displayedGraph=graph;
  $('#graph-detail').textContent='选择节点或关系，查看当前勾选论文的原文来源。';
  $('#graph-source').textContent=mode==='teaching'?'独立教学数据 · 非论文事实':mode==='candidate'?'抽取图谱 · 含待审核事实':`正式图谱 · ${graph.source||'已导入快照'}`;
  $('#graph-source').classList.toggle('warning',mode!=='official');
  const total=graphPaperOptions().length;
  $('#graph-paper-summary').textContent=`已勾选 ${selectedGraphPapers().length} / ${total} 篇论文 · 当前显示 ${graph.nodes.length} 个实体、${graph.edges.length} 条关系。`;
  $$('.segmented button').filter(el=>!el.hasAttribute('data-review-status')).forEach(el=>el.classList.remove('selected'));
  $(mode==='teaching'?'#example-graph':mode==='candidate'?'#candidate-graph':'#official-graph').classList.add('selected');
  $('#graph-type').innerHTML='<option value="">所有实体类型</option>'+Object.keys(colors).map(t=>`<option value="${t}">${t}</option>`).join('');
  $('#graph-legend').innerHTML=Object.entries(colors).map(([t,c])=>`<span><i style="background:${c}"></i>${t}</span>`).join('');
  if(cy)cy.destroy();cy=null;
  if(!graph.edges.length) {
    $('#main-graph').innerHTML=empty(selectedGraphPapers().length?'所选论文暂无可展示关系，请检查审核与导入状态。':'尚未勾选论文，请在上方选择要展示的论文。');return;
  }
  if(!window.cytoscape) {$('#main-graph').innerHTML=empty('图形组件未安装，请执行 setup/install.py');return;}
  cy=createGraph('main-graph',graph);
  filterGraph();
  setTimeout(()=>{cy?.resize();cy?.fit(undefined,35);},40);
}

async function copyPaperQuery() {
  if(graphMode==='candidate')return notify('抽取图谱尚未全部导入数据库，请切换正式图谱后复制查询。');
  const ids=selectedGraphPapers();
  const project=graphMode==='teaching'?'kg3dr-teaching':'kg3dr-course';
  const query=`MATCH (a:KG3DR {project:'${project}'})-[r]->(b:KG3DR {project:'${project}'})\nWHERE any(pid IN coalesce(r.paper_ids, []) WHERE pid IN ${JSON.stringify(ids)})\nRETURN a,r,b LIMIT 200;`;
  try {await navigator.clipboard.writeText(query);notify('已复制：在 Neo4j Browser 粘贴运行即可查看所选论文关系。');}
  catch (_) {openJSON('所选论文的 Neo4j 查询',{cypher:query},'复制 cypher 内容，到 Neo4j Browser 运行。点击保存仅关闭此窗口。',async()=>{});}
}

async function loadOfficialGraph() {
  graphNeedsRefresh=false;
  if(isStatic) return setGraph(state.graph,'official');
  try {setGraph(await api('/api/graph'),'official');}
  catch(error){setGraph(state.graph,'official');$('#graph-source').textContent='Neo4j 未连接 · 本地快照';notify(error.message);}
}
async function showTeaching() {
  try{const data=isStatic?window.KG_EXAMPLE:await api('/api/example');location.hash='graph';setGraph(data,'teaching');}
  catch(error){notify(error.message);}
}
function showCandidateGraph() {
  const nodes=new Map(),edges=[],evidence=[];
  candidateGroups.forEach(group=>{
    const rows=group.rows.filter(row=>row.status!=='rejected');
    if(!rows.length)return;
    nodes.set(group.subject.id,group.subject);nodes.set(group.object.id,group.object);
    edges.push({id:group.id,source:group.subject.id,target:group.object.id,
      relation:group.relation,evidence_ids:rows.map(row=>row.id),paper_ids:[...new Set(rows.map(row=>row.paper_id))]});
    rows.forEach(row=>evidence.push({id:row.id,paper_id:row.paper_id,
      page:row.candidate.page,quote:row.candidate.quote}));
  });
  setGraph({nodes:[...nodes.values()],edges,evidence,paper_ids:[...new Set(evidence.map(e=>e.paper_id))]},'candidate');
}

function showNode(node) {
  const related=displayedGraph.edges.filter(e=>e.source===node.id||e.target===node.id);
  $('#graph-detail').innerHTML=`<span class="pill">${escapeHTML(node.type)}</span><h3>${escapeHTML(node.name)}</h3><code>${escapeHTML(node.id)}</code><hr><p>${related.length} 条关联关系</p>`+related.slice(0,30).map(e=>`<p>${escapeHTML(e.relation)} → ${escapeHTML(displayedGraph.nodes.find(n=>n.id===(e.source===node.id?e.target:e.source))?.name)}</p>`).join('');
}
function showEdge(edge) {
  const evidence=displayedGraph.evidence.filter(e=>edge.evidence_ids?.includes(e.id));
  $('#graph-detail').innerHTML=`<h3>${escapeHTML(edge.relation)}</h3><code>${escapeHTML(edge.id)}</code><hr>`+evidence.map(e=>`<strong>${escapeHTML(e.paper_id)} · PDF 第 ${e.page} 页</strong><blockquote>${escapeHTML(e.quote)}</blockquote><small>证据 ${escapeHTML(e.id)}</small>${!isStatic&&graphMode!=='teaching'?`<p><a href="/api/pdf/${encodeURIComponent(e.paper_id)}#page=${e.page}" target="_blank" rel="noopener">查看原 PDF ↗</a></p>`:''}`).join('');
}

function showLocalCase() {
  const graph=selectedGraph();
  const components=graph.nodes.filter(n=>n.type==='Component');
  let chosen=[];let component=null;
  for(const candidate of components) {
    const methods=new Set(graph.edges.filter(e=>e.relation==='USES_COMPONENT'&&e.target===candidate.id).map(e=>e.source));
    const papers=new Set();const pairs=[];
    for(const edge of graph.edges.filter(e=>e.relation==='PROPOSES'&&methods.has(e.target))) {
      if(!papers.has(edge.source)){papers.add(edge.source);pairs.push(edge);}
    }
    if(pairs.length>=3){chosen=pairs.slice(0,3);component=candidate;break;}
  }
  if(!component)return notify('需要至少3篇论文的方法共享同一组件，当前图谱尚不足以形成该案例。');
  const ids=new Set([component.id,...chosen.flatMap(e=>[e.source,e.target])]);
  const methodIds=new Set(chosen.map(e=>e.target));
  for(const edge of graph.edges)if(methodIds.has(edge.source)&&['OUTPUTS','SOLVES','EVALUATED_ON'].includes(edge.relation))ids.add(edge.target);
  const edges=graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  const evidenceIds=new Set(edges.flatMap(e=>e.evidence_ids||[]));
  setGraph({...graph,nodes:graph.nodes.filter(n=>ids.has(n.id)),edges,evidence:graph.evidence.filter(e=>evidenceIds.has(e.id))},graphMode,true);
  $('#graph-detail').innerHTML='<h3>共享组件：'+escapeHTML(component.name)+'</h3><p>选取3篇论文及其方法，展示共同组件与输出/任务。共享组件不代表方法继承关系。</p><p>点击关系查看逐条证据。</p>';
  $('#graph-source').textContent+=' · 三论文局部案例';
}

function filterGraph() {
  if(!cy)return;
  const query=$('#graph-search').value.toLowerCase(),type=$('#graph-type').value;
  cy.elements().removeClass('dim');
  const nodes=cy.nodes().filter(n=>(!type||n.data('type')===type)&&(!query||(n.data('name')+' '+n.id()).toLowerCase().includes(query)));
  if(query||type){cy.elements().addClass('dim');nodes.closedNeighborhood().removeClass('dim');if(nodes.length)cy.fit(nodes.closedNeighborhood(),45);}
}
async function loadCandidates() {
  if(isStatic) return;
  candidateGroups=await api('/api/candidates?grouped=true');
  candidates=candidateGroups.flatMap(group=>group.rows);candidatesLoaded=true;renderCandidates();
}
function renderReviewPaperOptions() {
  const select=$('#review-paper'),previous=select.value;
  const titles=new Map(state.papers.map(p=>[p.paper_id,p.title]));
  const ids=new Set([...titles.keys(),...candidates.map(row=>row.paper_id)]);
  const html='<option value="">全部论文</option>'+[...ids].sort().map(id=>`<option value="${escapeHTML(id)}">${escapeHTML(id+' · '+(titles.get(id)||id))}</option>`).join('');
  if(select.innerHTML!==html){select.innerHTML=html;select.value=ids.has(previous)?previous:'';}
}

function renderCandidates() {
  renderReviewPaperOptions();
  if(location.hash==='#graph')loadEntityResolution().catch(error=>notify(error.message));
  const paperId=$('#review-paper').value;
  visibleReviewGroups=KGFilters.filterReviewGroups(candidateGroups,paperId,reviewStatus);
  const counts=KGFilters.reviewCounts(candidateGroups,paperId);
  $$('[data-review-status]').forEach(button=>{
    const status=button.dataset.reviewStatus;
    button.classList.toggle('selected',status===reviewStatus);
    button.setAttribute('aria-selected',String(status===reviewStatus));
    button.innerHTML=KGFilters.reviewLabels[status]+` <span class="tab-count">${counts[status]}</span>`;
  });
  const visibleRows=visibleReviewGroups.flatMap(group=>group.rows);
  $('#candidate-summary').textContent=`${paperId || '全部论文'} · ${KGFilters.reviewLabels[reviewStatus]}：${visibleReviewGroups.length} 个不同三元组、${visibleRows.length} 条证据。各来源独立审核，切换筛选不会修改审核记录。`;
  $('#select-all-facts').checked=false;$('#select-all-facts').indeterminate=false;
  $('#facts-body').innerHTML=visibleReviewGroups.map(group=>{
    const counts=Object.entries(group.status_counts).filter(([,count])=>count>0)
      .map(([status,count])=>`<span class="status-${status}">${KGFilters.reviewLabels[status]} ${count}</span>`).join('<br>');
    const evidence=group.rows.map(row=>`<div class="evidence-record"><label><input type="checkbox" class="fact-check" value="${escapeHTML(row.id)}" aria-label="选择此条证据"> ${escapeHTML(row.paper_id)} · 第 ${row.candidate.page} 页 <span class="status-${row.status}">${KGFilters.reviewLabels[row.status]}</span></label><blockquote>${escapeHTML(row.candidate.quote)}</blockquote><small>${escapeHTML(row.reviewer||'尚未审核')}</small><button data-edit-fact="${escapeHTML(row.id)}">核验 / 修改此证据</button></div>`).join('');
    return `<tr><td><input type="checkbox" class="group-check" data-group-id="${escapeHTML(group.id)}" aria-label="选择此三元组当前可见的证据"></td><td><strong>${escapeHTML(group.subject.name)}</strong><small>${escapeHTML(group.relation)}</small>${escapeHTML(group.object.name)}</td><td><details ${group.rows.length===1?'open':''}><summary>${group.rows.length} 条来源证据（展开逐条核对）</summary>${evidence}</details></td><td>${counts}</td><td>按证据独立审核</td></tr>`;
  }).join('')||`<tr><td colspan="5">${empty('当前论文范围下没有'+KGFilters.reviewLabels[reviewStatus]+'的三元组。')}</td></tr>`;
}

async function runStage(stage,extra={}) {
  try{const request={stage,...extra};if(extra.paper_id){const paper=state.papers.find(p=>p.paper_id===extra.paper_id);if(paper?.sha256)request.expected_paper_sha256=paper.sha256;}await api('/api/run',{method:'POST',body:JSON.stringify(request)});notify('任务已提交，可在下方查看运行记录');await refresh();}
  catch(error){notify(error.message);}
}
function updateJobItem(item,job) {
  const signature=JSON.stringify(job);
  if(item.jobSignature===signature)return;
  item.jobSignature=signature;
  let metadata=item.querySelector('.job-metadata');
  if(!metadata){metadata=document.createElement('div');metadata.className='job-metadata';item.append(metadata);}
  metadata.innerHTML=`<div class="job-head"><strong>${escapeHTML(stageNames[job.kind]||job.kind)}</strong><span class="pill ${job.status==='failed'?'warning':''}">${escapeHTML(job.status)}</span><time>${escapeHTML(new Date(job.created_at).toLocaleString())}</time></div>${job.total?`<progress value="${job.completed}" max="${job.total}"></progress>`:''}${job.error?`<p class="error">${escapeHTML(job.error)}</p>`:''}${job.logs?.length?`<p class="muted">${escapeHTML(job.logs.at(-1).message)}</p>`:''}`;
  let details=item.querySelector('details[data-job-output]');
  if(job.result!==undefined && job.result!==null) {
    if(!details) {
      details=document.createElement('details');details.dataset.jobOutput=job.id;
      const summary=document.createElement('summary');summary.textContent='查看此阶段输出';
      const pre=document.createElement('pre');pre.className='result-json';
      details.append(summary,pre);item.append(details);
    }
    const pre=details.querySelector('pre');
    const text=JSON.stringify(job.result,null,2);
    if(pre.textContent!==text) {
      const top=pre.scrollTop,left=pre.scrollLeft;
      pre.textContent=text;pre.scrollTop=top;pre.scrollLeft=left;
    }
  } else if(details)details.remove();
}

function renderJobs() {
  const jobs=(state.jobs||[]).slice(0,8),container=$('#jobs');
  const ids=new Set(jobs.map(job=>String(job.id)));
  // 按作业ID复用DOM，不能每4秒整体替换innerHTML，否则details.open和滚动位置都会丢失。
  for(const child of [...container.children])if(!ids.has(child.dataset.jobId))child.remove();
  const existing=new Map([...container.children].map(child=>[child.dataset.jobId,child]));
  jobs.forEach((job,index)=>{
    let item=existing.get(String(job.id));
    if(!item){item=document.createElement('div');item.className='job-item';item.dataset.jobId=String(job.id);}
    updateJobItem(item,job);
    const current=container.children[index];
    if(current!==item)container.insertBefore(item,current||null);
  });
  if(!jobs.length && !container.children.length)container.innerHTML=empty('尚无运行记录。每个阶段完成后都会保存产物。');
  const button=$('#clear-jobs');
  button.disabled=isStatic || clearingJobHistory || !(state.jobs||[]).some(job=>['complete','failed','interrupted'].includes(job.status));
  button.textContent=clearingJobHistory?'正在清除…':'清除已结束记录';
  button.title=isStatic?'静态展示只读，请在实时Demo清除运行记录':'清除已完成、失败和中断的记录；保留正在运行和排队的任务';
}

async function clearJobHistory() {
  if(isStatic)return notify('静态展示只读，请在实时Demo清除运行记录。');
  if(clearingJobHistory)return;
  clearingJobHistory=true;renderJobs();
  try {
    const result=await api('/api/jobs',{method:'DELETE'});
    await refresh();
    notify(`已清除 ${result.cleared} 条已结束记录${result.kept_active?`，保留 ${result.kept_active} 个正在运行或排队的任务`:''}。论文和实验结果保留。`);
  } catch(error) {notify(error.message);}
  finally {clearingJobHistory=false;renderJobs();}
}

function renderClassification() {
  const result=state.results.classification;
  if(!result){$('#classification-output').innerHTML=empty('尚无正式分类结果。请先核验图谱，并确认完整任务标签。');return;}
  if(result.status!=='complete'){$('#classification-output').innerHTML=`<div class="card"><h2>数据尚不足以正式评测</h2><p>${escapeHTML(result.message)}</p>${jsonDetails(result,'查看类别与样本缺口')}</div>`;return;}
  $('#classification-output').innerHTML=`<div class="card"><div class="card-heading"><h2>留一交叉验证结果</h2><span class="micro">${result.papers.length} 篇 · ${result.tasks.length} 个标签 · ${result.graph_version.slice(0,10)}</span></div>${staleNotice(result)}<table><thead><tr><th>方法</th><th>Micro-F1</th><th>Macro-F1</th></tr></thead><tbody>${Object.entries(result.modes).map(([mode,r])=>`<tr><td>${escapeHTML(mode)}</td><td>${r.micro_f1.toFixed(3)}</td><td>${r.macro_f1.toFixed(3)}</td></tr>`).join('')}</tbody></table><p class="muted">${escapeHTML(result.limitations)}</p>${jsonDetails(result,'查看逐类、逐例与防泄漏分析')}</div>`;
}
function renderSingleClassification(result) {if(!result)return;$('#classify-single').innerHTML=`<div class="card"><h2>单篇预测 · ${escapeHTML(result.paper_id)}</h2><p class="notice">${escapeHTML(result.note)} ${result.in_training_set?'该论文已在全量模型训练集中。':''}</p>${result.predictions.map(p=>`<p>${escapeHTML(nodeName(p.task_id))} <strong>${p.score.toFixed(3)}</strong></p>`).join('')}${jsonDetails(result.features,'查看实际图谱特征')}</div>`;}
function renderPrediction() {
  renderRelationWorkspace();
  const result=state.results.prediction;
  if(!result){$('#prediction-output').innerHTML=empty('尚无正式关系预测评测。先建立包含组件关系的已审核图谱。');return;}
  $('#prediction-output').innerHTML=`<div class="card"><h2>按论文分组留出</h2>${staleNotice(result)}<div class="metric-grid">${metric('路径 MRR',result.path_model?.mrr)}${metric('Hits@1',result.path_model?.hits_at_1)}${metric('Hits@3',result.path_model?.hits_at_3)}${metric('候选覆盖率',result.path_model?.coverage)}</div><p>频率基线 MRR：${result.frequency_baseline?.mrr?.toFixed(3)||'—'}</p><p class="muted">${escapeHTML(result.limitations)}</p>${jsonDetails(result,'查看隐藏边、候选路径与失败案例')}</div>`;
}
function renderSinglePrediction(result) {if(!result)return;$('#predict-single').innerHTML=`<div class="card"><h2>待核验的组件建议</h2><p class="notice">${escapeHTML(result.note)}</p>${result.candidates.length?`<table><thead><tr><th>候选组件</th><th>路径分数</th><th>图谱路径</th></tr></thead><tbody>${result.candidates.map(c=>`<tr><td>${escapeHTML(c.name)}</td><td>${c.score}</td><td>${c.paths.map(p=>p.map(n=>escapeHTML(n.name)).join(' → ')).join('<br>')||'未发现短路径，分数为零'}</td></tr>`).join('')}</tbody></table>`:empty('训练图谱中没有可推荐的新组件')}${jsonDetails(result)}</div>`;}
function openJSON(title,data,help,onSave) {
  $('#editor-title').textContent=title;$('#editor-help').textContent=help;$('#editor-fields').innerHTML='';$('#editor-json').hidden=false;$('#editor-json').value=JSON.stringify(data,null,2);$('#editor-error').textContent='';
  editorSave=async()=>onSave(JSON.parse($('#editor-json').value));$('#editor-dialog').showModal();
}
function editPaper(id) {
  const paper=state.papers.find(p=>p.paper_id===id);if(!paper)return;
  $('#editor-title').textContent='编辑论文 '+id;$('#editor-help').textContent='标题应与正文一致；发表年份不要直接采用 PDF 创建时间。';$('#editor-json').hidden=true;$('#editor-error').textContent='';
  const fields={title:'标题',authors:'作者',year:'发表年份',venue:'发表出处',doi_or_arxiv:'DOI / arXiv',url:'论文链接',topic_tags:'主题标签',inclusion_reason:'筛选依据',status:'整理状态'};
  $('#editor-fields').innerHTML=Object.entries(fields).map(([key,label])=>`<label>${label}<input name="${key}" value="${escapeHTML(paper[key]||'')}"></label>`).join('')+`<label>纳入正式语料<select name="included"><option value="true" ${paper.included!==false?'selected':''}>是</option><option value="false" ${paper.included===false?'selected':''}>否</option></select></label>`;
  editorSave=async()=>{const payload={expected_sha256:paper.sha256};$('#editor-fields').querySelectorAll('[name]').forEach(input=>payload[input.name]=input.name==='included'?input.value==='true':input.value);await api('/api/papers/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify(payload)});await refresh();};$('#editor-dialog').showModal();
}
async function deletePaper(id) {
  const paper=state.papers.find(p=>p.paper_id===id);
  if(!paper)return;
  if(isStatic)return notify('静态展示不能删除，请连接实时服务。');
  if(!window.confirm(`删除 ${id}：${paper.title}？\n\n将清理项目内PDF、解析、抽取、审核、缓存及该论文的图谱证据。共享事实会保留其他来源；后续论文编号会依次前移。旧实验与导出成果将失效，删除内容先备份到服务器本地。`))return;
  const button=$(`[data-delete-paper="${CSS.escape(id)}"]`);
  if(button)button.disabled=true;
  try {
    const result=await api('/api/papers/'+encodeURIComponent(id)+'?expected_sha256='+encodeURIComponent(paper.sha256),{method:'DELETE'});
    await refresh();await loadCandidates();
    fullGraph=null;graphNeedsRefresh=true;
    setGraph(state.graph,'official');
    $('#graph-detail').textContent='论文已删除。共享实体与关系保留其他论文证据。';
    $('#classify-single').innerHTML='';$('#predict-single').innerHTML='';
    notify(`已删除 ${id}，剩余论文已连续编号。备份目录：${result.backup}`);
  } catch(error) {notify(error.message);if(button)button.disabled=false;}
}

function editFact(id) {
  const row=candidates.find(f=>f.id===id);if(!row)return;
  openJSON('核验事实 '+id,{status:row.status,reviewer:$('#reviewer').value||row.reviewer||'',note:row.note||'',candidate:row.candidate},'核对论文原文后修改 candidate；status 可为 approved / rejected / pending。审核者不可为空。',async value=>{await api('/api/review/'+id,{method:'PUT',body:JSON.stringify(value)});await loadCandidates();await refresh();});
}
async function bulkReview(status) {
  const ids=$$('.fact-check:checked').map(e=>e.value),reviewer=$('#reviewer').value.trim();
  if(!ids.length||!reviewer)return notify('请选择已核对的证据并填写审核者');
  try{await api('/api/review-bulk',{method:'POST',body:JSON.stringify({ids,status,reviewer,note:'人工批量审核'})});await loadCandidates();await refresh();notify('审核记录已保存');}catch(error){notify(error.message);}
}

initEntityResolution();
initRelationPrediction();

// 事件集中注册：阅读时从按钮追踪到 runStage，再到 backend 的 /api/run。
$$('[data-run]').forEach(button=>button.addEventListener('click',()=>runStage(button.dataset.run,button.dataset.run==='parse'?{paper_id:$('#extract-paper').value||null}:{})));
$('#pipeline-button').onclick=()=>runStage('pipeline',{paper_id:$('#extract-paper').value||null});
$('#import-button').onclick=()=>runStage('import');
$('#classify-button').onclick=()=>$('#classify-paper').value?runStage('classify',{paper_id:$('#classify-paper').value}):notify('请选择论文');
$('#predict-button').onclick=()=>$('#predict-method').value?runStage('predict',{method_id:$('#predict-method').value}):notify('请选择方法');
$('#ask-button').onclick=submitGeneration;
function renderSelectedFiles() {
  const files=[...$('#pdf-input').files];
  $('#file-count').textContent=files.length?`已选择 ${files.length} 个文件`:'未选择文件';
  $('#selected-files').hidden=files.length===0;
  // 文件名是用户输入，使用textContent展示，避免被解释为HTML。
  $('#selected-file-list').replaceChildren(...files.map(file=>{
    const item=document.createElement('li');item.textContent=file.name;return item;
  }));
}
$('#pdf-input').onchange=renderSelectedFiles;
$('#upload-button').onclick=async()=>{const files=$('#pdf-input').files;if(!files.length)return notify('先选择 PDF 文件');const form=new FormData();for(const file of files)form.append('files',file);try{const r=await api('/api/upload',{method:'POST',body:form});notify(`上传 ${r.stored.length} 篇，重复 ${r.duplicates.length} 篇，失败 ${r.failures.length} 篇${r.failures.length?'：'+r.failures[0].error:''}`);}catch(error){notify(error.message);}};
$('#papers-body').onclick=event=>{const remove=event.target.closest('[data-delete-paper]');if(remove){deletePaper(remove.dataset.deletePaper);return;}const button=event.target.closest('[data-edit-paper]');if(button)editPaper(button.dataset.editPaper);};
$('#facts-body').onclick=event=>{const button=event.target.closest('[data-edit-fact]');if(button)editFact(button.dataset.editFact);};
$('#select-all-facts').onchange=event=>$$('.fact-check,.group-check').forEach(box=>box.checked=event.target.checked);
$('#facts-body').onchange=event=>{
  if(event.target.matches('.group-check')) {
    const group=visibleReviewGroups.find(g=>g.id===event.target.dataset.groupId);
    const ids=new Set(group.rows.map(row=>row.id));
    $$('.fact-check').filter(box=>ids.has(box.value)).forEach(box=>box.checked=event.target.checked);
  }
};
$('#approve-selected').onclick=()=>bulkReview('approved');$('#reject-selected').onclick=()=>bulkReview('rejected');
$('#refresh-candidates').onclick=()=>loadCandidates().catch(e=>notify(e.message));
$('#review-paper').onchange=renderCandidates;
$$('[data-review-status]').forEach(button=>button.onclick=()=>{reviewStatus=button.dataset.reviewStatus;renderCandidates();});
$('#graph-paper-options').onchange=event=>{
  if(event.target.matches('.graph-paper-check')){
    const ids=$$('.graph-paper-check:checked').map(box=>box.value);
    changeGraphPapers(ids,ids.length===graphPaperOptions().length);
  }
};
$('#graph-papers-all').onclick=()=>changeGraphPapers([],true);
$('#graph-papers-none').onclick=()=>changeGraphPapers([],false);
$('#copy-paper-query').onclick=copyPaperQuery;
$('#save-aliases').onclick=async()=>{try{await api('/api/aliases',{method:'PUT',body:JSON.stringify(JSON.parse($('#aliases-editor').value))});await loadCandidates();await refresh();await loadEntityResolution(true);notify('别名已保存，重新校验并导入后生效');}catch(e){notify(e.message);}};
$('#edit-labels').onclick=loadLabelReview;
$('#classification-advanced').addEventListener('toggle',()=>{if($('#classification-advanced').open && !labelReview)loadLabelReview(false);});
$('#reload-labels').onclick=()=>{if(!labelDirty.size || confirm('重新加载会放弃尚未确认的标签修改，继续吗？'))loadLabelReview();};
$('#label-search').oninput=filterLabelPapers;$('#label-status').onchange=filterLabelPapers;
$('#edit-questions').onclick=editGenerationQuestions;
$('#review-generation').onclick=reviewGeneration;
$('#editor-form').onsubmit=async event=>{event.preventDefault();try{await editorSave();$('#editor-dialog').close();}catch(error){$('#editor-error').textContent=error.message;}};
$('#close-dialog').onclick=()=>$('#editor-dialog').close();$('#refresh-state').onclick=refresh;
$('#clear-jobs').onclick=clearJobHistory;
$('#official-graph').onclick=loadOfficialGraph;$('#candidate-graph').onclick=async()=>{try{await loadCandidates();showCandidateGraph();}catch(e){notify(e.message);}};
$('#example-graph').onclick=showTeaching;$('#teaching-button').onclick=showTeaching;
$('#graph-search').oninput=filterGraph;$('#graph-type').onchange=filterGraph;
$('#local-case').onclick=showLocalCase;
$('#graph-reset').onclick=()=>{if(fullGraph)setGraph(fullGraph,graphMode);if(cy){cy.elements().removeClass('dim');cy.fit(undefined,35);}$('#graph-search').value='';$('#graph-type').value='';};

async function loadLabelReview(scroll=true) {
  if(labelReview && labelDirty.size && this?.id==='edit-labels') {
    $('#label-review').hidden=false;$('#label-review').scrollIntoView({behavior:'smooth'});return;
  }
  const button=$('#edit-labels');button.disabled=true;button.textContent='正在读取标签…';
  try {
    const data=isStatic?window.KG_STATIC?.label_review:await api('/api/labels');
    if(!data)throw new Error('该静态快照不含标签审核数据，请打开实时 Demo 或重新导出。');
    labelReview=data;labelDirty.clear();
    labelReview.selections=Object.fromEntries(Object.entries(data.labels).map(([id,row])=>[id,new Set(row.task_ids)]));
    labelReview.notes=Object.fromEntries(Object.entries(data.labels).map(([id,row])=>[id,row.note||'']));
    $('#label-review').hidden=false;
    renderLabelReview();
    if(scroll!==false)$('#label-review').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(error){notify(error.message);}
  finally{button.disabled=false;button.textContent='审核论文标签';}
}
function labelTaskName(id) {return labelReview.tasks.find(t=>t.id===id)?.name || id;}
function labelPaperCard(id) {
  const row=labelReview.labels[id], selected=labelReview.selections[id];
  const paper=labelReview.papers.find(p=>p.paper_id===id);
  const suggestions=labelReview.suggestions[id]?.task_ids||[];
  const confirmed=row.verified && row.reviewer && !labelDirty.has(id);
  return `<article class="label-paper" data-label-paper="${escapeHTML(id)}">
    <div class="card-heading"><h3>${escapeHTML(id)} · ${escapeHTML(paper?.title||id)}</h3><span class="pill ${confirmed?'':'warning'}">${confirmed?'已确认 · '+escapeHTML(row.reviewer):labelDirty.has(id)?'已修改，待确认':'待确认'}</span></div>
    <p class="micro">图谱建议（待人工核对）</p><div class="label-chips">${suggestions.map(t=>`<button type="button" data-label-add="${escapeHTML(t)}" ${selected.has(t)?'disabled':''}>＋ ${escapeHTML(labelTaskName(t))}</button>`).join('')||'<span class="muted">暂无建议，请从全部任务中选择；无关系不代表不研究该任务。</span>'}</div>
    <p class="micro">当前选择 · ${selected.size} 个标签（点击 × 移除）</p><div class="label-chips">${[...selected].map(t=>`<button type="button" class="label-chip" data-label-remove="${escapeHTML(t)}" aria-label="移除 ${escapeHTML(labelTaskName(t))}">${escapeHTML(labelTaskName(t))} ×</button>`).join('')||'<span class="muted">尚未选择任务标签</span>'}</div>
    <details><summary>从全部 ${labelReview.tasks.length} 个任务中添加或移除</summary><div class="label-options">${labelReview.tasks.map(t=>`<label title="${escapeHTML(t.id)}"><input type="checkbox" data-label-task="${escapeHTML(t.id)}" ${selected.has(t.id)?'checked':''}>${escapeHTML(t.name)}</label>`).join('')||'<p>当前图谱没有任务节点，请先补充并审核任务关系，再导入图谱。</p>'}</div></details>
    <div class="label-toolbar"><label>审核备注<input data-label-note value="${escapeHTML(labelReview.notes[id])}" placeholder="可选：标签修改依据"></label><a href="/api/pdf/${encodeURIComponent(id)}" target="_blank" rel="noopener">查看论文原文 ↗</a><button type="button" class="primary" data-label-confirm ${confirmed?'disabled':''}>${confirmed?'已确认生效':'确认此篇标签'}</button></div>
    <p class="label-error error" role="alert"></p>
  </article>`;
}
function renderLabelReview() {
  $('#label-paper-list').innerHTML=Object.keys(labelReview.labels).map(labelPaperCard).join('')||empty('当前图谱没有论文，请先审核事实并导入图谱。');
  renderLabelCatalog();filterLabelPapers();
  if(isStatic){
    $('#label-progress').prepend('静态快照仅供查看；请在实时 Demo 中修改和确认标签。 ');
    $$('#label-paper-list input, #label-paper-list button, #label-reviewer').forEach(el=>el.disabled=true);
  }
}
function renderLabelCatalog() {
  const rows=Object.values(labelReview.labels).filter(row=>row.verified && row.reviewer);
  $('#label-progress').textContent=`已确认 ${rows.length} / ${Object.keys(labelReview.labels).length} 篇。确认后立即保存；修改后的标签需再次确认。样本统计以已保存标签为准。`;
  $('#label-catalog').innerHTML='<table><thead><tr><th>全部任务标签</th><th>已确认正例</th><th>已确认负例</th><th>评测条件</th></tr></thead><tbody>'+labelReview.tasks.map(task=>{
    const positive=rows.filter(row=>row.task_ids.includes(task.id)).length, negative=rows.length-positive;
    const gap=positive>=5 && negative>=5?'可评测':`还需 ${Math.max(0,5-positive)} 篇正例、${Math.max(0,5-negative)} 篇负例`;
    return `<tr><td>${escapeHTML(task.name)}</td><td>${positive}</td><td>${negative}</td><td>${gap}</td></tr>`;
  }).join('')+'</tbody></table>';
}
function filterLabelPapers() {
  if(!labelReview)return;
  const query=$('#label-search').value.trim().toLowerCase(),status=$('#label-status').value;
  $$('#label-paper-list [data-label-paper]').forEach(card=>{
    const id=card.dataset.labelPaper,row=labelReview.labels[id];
    const verified=!!(row.verified && row.reviewer && !labelDirty.has(id));
    const paper=labelReview.papers.find(p=>p.paper_id===id);
    card.hidden=!(id+' '+(paper?.title||'')).toLowerCase().includes(query) || (status==='verified'&&!verified) || (status==='pending'&&verified);
  });
}
function updateLabelSelection(card,task,add) {
  const id=card.dataset.labelPaper;
  if(add)labelReview.selections[id].add(task);else labelReview.selections[id].delete(task);
  labelDirty.add(id);
  const open=card.querySelector('details').open;
  card.outerHTML=labelPaperCard(id);
  const updated=$$('#label-paper-list [data-label-paper]').find(c=>c.dataset.labelPaper===id);
  updated.querySelector('details').open=open;
  const input=[...updated.querySelectorAll('[data-label-task]')].find(e=>e.dataset.labelTask===task);
  if(open)input?.focus();
  filterLabelPapers();
}
$('#label-paper-list').onchange=event=>{
  const card=event.target.closest('[data-label-paper]');if(!card)return;
  if(event.target.matches('[data-label-task]'))updateLabelSelection(card,event.target.dataset.labelTask,event.target.checked);
};
$('#label-paper-list').oninput=event=>{
  if(!event.target.matches('[data-label-note]'))return;
  const card=event.target.closest('[data-label-paper]'),id=card.dataset.labelPaper;
  labelReview.notes[id]=event.target.value;labelDirty.add(id);
  const button=card.querySelector('[data-label-confirm]');button.disabled=false;button.textContent='确认此篇标签';
  card.querySelector('.pill').textContent='已修改，待确认';filterLabelPapers();
};
$('#label-paper-list').onclick=async event=>{
  const button=event.target.closest('button'),card=button?.closest('[data-label-paper]');if(!card)return;
  if(button.hasAttribute('data-label-add'))return updateLabelSelection(card,button.dataset.labelAdd,true);
  if(button.hasAttribute('data-label-remove'))return updateLabelSelection(card,button.dataset.labelRemove,false);
  if(!button.hasAttribute('data-label-confirm'))return;
  const error=card.querySelector('.label-error'),reviewer=$('#label-reviewer').value.trim(),id=card.dataset.labelPaper;
  error.textContent='';
  if(!reviewer){error.textContent='请先在上方填写审核者姓名。';$('#label-reviewer').focus();return;}
  if(!labelReview.selections[id].size && !confirm('此篇未选择任何任务。确认后将作为全部任务的负例，确定标签已核对完整吗？'))return;
  button.disabled=true;button.textContent='正在保存…';
  // 保存期间禁止修改当前论文，避免后到的响应覆盖新的编辑。
  card.querySelectorAll('input,button').forEach(el=>el.disabled=true);
  try {
    const result=await api('/api/labels/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify({task_ids:[...labelReview.selections[id]],reviewer,note:labelReview.notes[id],graph_version:labelReview.graph_version})});
    labelReview.labels[id]=result.label;labelDirty.delete(id);card.outerHTML=labelPaperCard(id);
    renderLabelCatalog();filterLabelPapers();notify(id+' 标签已确认并保存');
  } catch(e){card.outerHTML=labelPaperCard(id);const current=$$('#label-paper-list [data-label-paper]').find(c=>c.dataset.labelPaper===id);current.querySelector('.label-error').textContent=e.message;filterLabelPapers();}
};

async function init() {
  initGenerationUI();
  initAutomaticUI();
  initTaxonomyHistoryUI();
  if(isStatic) {
    candidateGroups=window.KG_STATIC?.candidate_groups || [];candidates=candidateGroups.flatMap(g=>g.rows);renderCandidates();
    $('#mode-text').textContent='离线静态快照';$('#connection').textContent='静态展示 · 只读';
    $('#csv-link').onclick=event=>{event.preventDefault();notify('CSV 清单请在实时服务导出。');};
    $$('[data-download]').forEach(link=>{link.href='../'+link.dataset.download;});
  } else {
    try{const health=await api('/api/health');$('#connection').textContent=health.deepseek_configured?'DeepSeek 已配置':'DeepSeek 待配置';$('#connection').classList.toggle('warning',!health.deepseek_configured);$('#neo-link').href=health.neo4j_browser;}catch(e){notify(e.message);}
  }
  await refresh();navigate();if(!isStatic)setInterval(async()=>{if(document.hidden||polling)return;polling=true;try{await refresh();}finally{polling=false;}},4000);
}
init().catch(error=>notify(error.message));
