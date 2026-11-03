'use strict';
let productionBatch=null,productionStore='';
let productionBrowserStatus=null;
const productionSlotsLatest=['m1','m2','m3','m4','m5','m6','d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9'];
const productionSlotsLegacy=['m1','m2','m3','m4','m5','m6','m7','d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9'];
function productionTemplateCount(p){for(const a of [p?.visualPartial,p?.visualPending,p?.visual])if(a?.revision===p?.revision){if(Number.isInteger(a.templateCount))return a.templateCount;return 19}return 18}
function productionSlotsFor(p){return productionTemplateCount(p)===19?productionSlotsLegacy:productionSlotsLatest}
const productionSteps=['资料与属性方案','新品包装','套图制作','图片审核','属性确认','草稿填写','保存与回读'];
const productionHeroPolicy='single-hero-v1';
const productionHeroSteps=['首图生成','查看实际首图','确认首图并自动制作到草稿','草稿待用户检查','自行后台发布 / 同步状态'];
const productionStates={WAITING_HERO_REVIEW:'首图待确认',HERO_REVIEW:'首图待确认',ACTIVE:'连续制作中',WAITING_PACKAGING_REVIEW:'待包装审核',WAITING_VISUAL_REVIEW:'待套图审核',WAITING_ATTRIBUTES_REVIEW:'待属性确认',NEEDS_INPUT:'待补资料',NEEDS_ATTENTION:'需要处理',STOPPED:'后续交接已停止',STALE:'资料变化，需重新预检',DRAFT_SAVED:'草稿已保存并回读',VISUALS_READY:'仅图片制作与审核完成'};
function productionSource(p){return p.recruitment?'征品参考':p.source?.startsWith('selection:')?'选品参考':'新品需求'}
function productionViewer(){return typeof teamViewOnly==='function'&&teamViewOnly()}
function productionProduct(id){return executionData?.products?.find(p=>p.id===id)}
function productionBrowserNote(state=productionBrowserStatus){
 const labels={DISCONNECTED:'未连接',CONNECTING:'等待后台页',LOGIN_REQUIRED:'需要登录',READY:'连接就绪'};
 return `<p class="execution-note">上品连接：${esc(labels[state?.status]||'尚未检查')} · ${esc(state?.message||'执行上品时会自动尝试恢复原Skill专用窗口；实际写入前仍核验店铺')}${state?.checkedAt?` · 最近检查 ${esc(state.checkedAt)}`:''}</p>`;
}
function productionResumeJob(p){
 if(!p)return null;
 const jobs=executionData?.jobs||[];
 const candidates=jobs.filter(job=>job.product===p.id&&job.revision===p.revision&&job.status==='NEEDS_ATTENTION'&&job.imageProvider==='codex-native'&&['hero','visual'].includes(job.kind)).filter(job=>{
  if(job.recoveryRequired||job.executorStillRunning)return true;
  const asset=p[job.kind],completed=asset&&jobs.find(row=>row.id===asset.job&&row.product===p.id&&row.revision===p.revision&&row.kind===job.kind&&row.status==='SUCCESS');
  return !(completed&&asset.revision===p.revision&&p.attributePlan?.fingerprint&&asset.attributePlanFingerprint===p.attributePlan.fingerprint&&Date.parse(completed.created)>Date.parse(job.created));
 })
  .sort((a,b)=>(Date.parse(b.updated||b.created)||0)-(Date.parse(a.updated||a.created)||0));
 return candidates.find(job=>job.id===p.workflow?.resumeJob)||candidates[0]||null;
}
function productionPolicy(p){return p.workflow?p.workflow.approvalPolicy:productionHeroPolicy}
function productionHeroCurrent(p){const h=p.hero;return h?.revision===p.revision&&p.attributePlan?.fingerprint&&h.attributePlanFingerprint===p.attributePlan.fingerprint&&h.templateVerified===true&&h.pixelHash&&h.images?.some(row=>row.slot==='m1')}
function productionHeroActions(p,viewer,active){return `${p.workflow?.status==='WAITING_HERO_REVIEW'?`<button class="button primary" data-action="flow-hero-review" data-id="${esc(p.id)}" ${viewer||active||!productionHeroCurrent(p)?'disabled':''}>查看实际首图并确认</button>`:''}<button class="button" data-action="flow-attributes" data-id="${esc(p.id)}" ${viewer||active?'disabled':''}>查看 / 修改属性方案</button><p class="execution-note">首图确认一次后，${p.workflow?.target==='VISUALS'?'自动完成套图和机器质检，仅图片完成后停止，不保存草稿':'自动完成套图、机器质检和草稿保存'}；未知事实或质检失败会停止并显示需处理。</p>`}
function productionPublication(p){
 const state=p.publication||{},authority=state.authority||{};
 const verified=authority.identity_verified===true&&authority.method==='GET'&&state.store===p.facts.store&&state.checked_at&&authority.source_url&&p.draft?.draft_id&&state.draft_id===String(p.draft.draft_id)&&state.product_id===String(p.draft.product_id||p.draft.draft_id);
 const label=verified&&state.status==='published'&&state.published===true?'已发布':verified&&state.status==='draft'?'平台状态：草稿':verified&&state.status==='unpublished'?'平台状态：未发布':'发布状态待同步 / 未知';
 return `<div class="production-message"><strong>${label}</strong><p>${esc(state.reason||'请在后台检查草稿并自行点击发布，再刷新实际平台状态。')}</p>${state.checked_at?`<small>读取时间：${esc(state.checked_at)} · 店铺：${esc(state.store||'未核实')}</small>`:''}<button class="button" data-action="flow-publication-refresh" data-id="${esc(p.id)}" ${productionViewer()?'disabled':''}>刷新发布状态</button></div>`;
}
function productionSpecificationPending(row,asset){return !['ok','not_applicable'].includes(row.specCheck)||row.reviewRequirements?.includes('specification')||row.quality?.reviewRequired===true||asset.quality?.reviewRequired===true}
function productionOutputs(p){
 const rows=new Map();
 if(productionHeroCurrent(p)){const row=p.hero.images.find(row=>row.slot==='m1');rows.set('m1',{...row,job:p.hero.job,state:p.workflow?.status==='WAITING_HERO_REVIEW'?'首图待确认':'首图已生成'})}
 for(const kind of ['visualPending','visualPartial','visual']){
  const asset=p[kind];if(asset?.revision!==p.revision)continue;
  for(const row of asset.images||[])rows.set(row.slot,{...row,job:asset.job,state:asset.needsRegeneration?'旧方案待重做':productionSpecificationPending(row,asset)?(p.workflow?.approvalPolicy===productionHeroPolicy?'规格质检待处理':'待核验 · 待人工规格核对'):kind==='visualPending'?'待核验':kind==='visualPartial'?'模块已渲染':'套图已核验'});
 }
 return rows;
}
function productionAssetURL(asset,row){return '/task-assets/'+encodeURIComponent(asset.job)+'/'+row.file.split('/').map(encodeURIComponent).join('/')}
function productionTemplateButtons(p){return (p.templatePreviews||[]).length?`<div class="production-actions">${p.templatePreviews.map(row=>`<button class="button" data-action="flow-template" data-id="${esc(p.id)}" data-slot="${esc(row.slot)}">${esc(row.slot)} 模板位置对照</button>`).join('')}</div>`:''}
function productionListingSkillResult(p){
 const result=p.listingSkill;if(result?.revision!==p.revision||result.attributePlanFingerprint!==p.attributePlan?.fingerprint||result.visualJob!==p.visual?.job)return '';
 if(p.draft?.readback_verified===true&&p.draft.revision===p.revision&&p.draft.store===p.facts?.store)
  return `<p class="production-message">草稿已保存并回读；原Skill内容预检为本次保存前记录${result.allowMissingNetWeight?'；净重按要求留空':''}。<br><small>最终字段值和后台链接见下方草稿回读；图片分区及顺序仍需后台终检。</small></p>`;
 const preflight=result.content_preflight||{},statuses={READY:'预检完成',BLOCKED:'预检待处理',FAILED:'预检未通过'};
 const fields=(result.field_replacements||[]).map(row=>`${row.key||'字段'}：${Array.isArray(row.to)?row.to.join(' / '):row.to??'待核验'}${row.requirement?'（征品要求：'+row.requirement+'）':''}`);
 const pending=(result.pending_requirements||[]).map(row=>typeof row==='string'?row:row.requirement||row.name||row.key||row.field||row.code||'待核验');
 return `<p class="production-message">${esc(result.message||'原Skill上品预检结果')} · ${esc(statuses[result.status]||'预检未完成')}<br><small>内容预检：${esc(({PASS:'通过',BLOCKED:'待处理',FAILED:'未通过'})[preflight.status]||'预检未完成')} · 字段替换：${esc(fields.length?fields.join('；'):'未返回替换项')}${pending.length?' · 待核验：'+esc(pending.join('；')):''}${preflight.blockingDiagnostics?.length?' · 内容异常：'+esc(preflight.blockingDiagnostics.join('；')):''} · 图片 ${esc(result.images??'待核验')} 张；草稿保存与回读以实际记录为准。</small></p>`;
}
function productionPanel(p,requestedTarget='DRAFT'){
 const viewer=productionViewer(),flow=p.workflow||{},plan=p.workflowPlan||{},rows=productionOutputs(p);
 const single=flow.approvalPolicy===productionHeroPolicy;
 const active=executionData?.jobs?.some(j=>j.product===p.id&&['QUEUED','RUNNING'].includes(j.status));
 const pack=p.packaging?.revision===p.revision?p.packaging:null,visual=p.visual?.revision===p.revision?p.visual:null;
 const blocked=[...new Set([...(flow.gaps||[]),...(plan.gaps||[])])].filter(row=>!(plan.advisories||[]).includes(row)).join('、');
 const resumeJob=productionResumeJob(p);
 const recovery=executionData?.jobs?.find(j=>j.product===p.id&&j.status==='NEEDS_ATTENTION'&&(j.recoveryRequired||j.id===resumeJob?.id));
 const target=requestedTarget==='VISUALS'?'VISUALS':'DRAFT',draftExists=Boolean(p.draft||p.draftHistory?.length);
 return `<section class="panel production-panel"><div class="production-heading"><div><span class="eyebrow">NEW PRODUCT WORKFLOW</span><h2>新品制作主任务</h2><p>${esc(productionSource(p))} · ${esc(p.facts.store||'目标店铺待选择')} · ${esc(p.id)} · V${p.revision}</p></div><span class="pill">${esc(productionStates[flow.status]||'尚未启动主任务')}</span></div><div class="production-stage-track">${(single?(target==='VISUALS'?['首图生成','查看实际首图','确认首图并制作完整套图','仅图片完成']:productionHeroSteps):target==='VISUALS'?productionSteps.slice(0,4):productionSteps).map((s,i)=>`<span>${i+1}. ${s}</span>`).join('')}</div><div class="production-message"><strong>${esc(flow.message||plan.message||(flow.target==='VISUALS'?'共用原Skill新品流程；仅图片审核完成后停止，不自动上品。':'三个入口共用原Skill新品流程，终点为后台草稿。'))}</strong>${blocked?`<p>需处理：${esc(blocked)}</p>`:''}${viewer?'<p>当前为只读查看身份，执行由本机管理员操作。</p>':''}</div><div class="production-actions"><button class="button primary" data-action="flow-preview" data-id="${esc(p.id)}" data-target="${target}" ${viewer||active||resumeJob||(target==='DRAFT'&&draftExists)?'disabled':''}>${target==='VISUALS'?'仅制作图片 / 预检':draftExists?'已有草稿，请核对回读':flow.target==='VISUALS'?'用当前图片生成草稿 / 预检':'一键生图并保存草稿'}</button>${flow.status?`<button class="button" data-action="flow-stop" data-id="${esc(p.id)}" ${viewer?'disabled':''}>停止后续交接</button>`:''}${single?productionHeroActions(p,viewer,active):`<button class="button" data-action="flow-attributes" data-id="${esc(p.id)}" ${viewer||active?'disabled':''}>${p.attributePlan?'查看 / 确认属性方案':'先准备属性方案'}</button>${p.designReview?.revision===p.revision&&!pack?`<button class="button" data-action="hub-design-review" data-id="${esc(p.id)}" ${viewer?'disabled':''}>确认包装设计稿</button>`:''}${pack&&p.approvedPackaging!==pack.job?`<button class="button" data-action="execution-approve" data-phase="packaging" data-id="${esc(p.id)}" ${viewer?'disabled':''}>审核当前包装</button>`:''}${visual&&p.approvedVisual!==visual.job?`<button class="button" data-action="execution-approve" data-phase="visual" data-id="${esc(p.id)}" ${viewer?'disabled':''}>审核当前套图</button>`:''}`}${resumeJob?`<button class="button" data-action="flow-native" data-id="${esc(p.id)}" data-job="${esc(resumeJob.id)}" ${viewer||active||resumeJob.executorStillRunning?'disabled':''}>恢复原任务与缓存</button>`:''}</div>${recovery?`<button class="button" data-action="flow-reconcile" data-id="${esc(p.id)}" data-job="${esc(recovery.id)}" ${viewer?'disabled':''}>核对已有产物 / 草稿</button>`:''}${active?'<p class="muted">已有任务执行中；重复启动不会新建相同任务。</p>':''}<p class="execution-note">优先复用当前版本已完成的套图；异常与待核验项由系统列明，不因切换板块重新制作或重复索取资料。</p><div class="production-preview-heading"><h3>固定模板进度与预览</h3><span>已生成 ${rows.size}/${productionTemplateCount(p)} · 生成、核验、审核分别记录</span></div><div class="production-slot-grid">${productionSlotsFor(p).map(slot=>{const row=rows.get(slot);return row?`<a class="production-slot" href="${productionAssetURL(row,row)}" target="_blank" rel="noopener"><img src="${productionAssetURL(row,row)}" loading="lazy" alt="${esc(slot)}"><strong>${slot}</strong><small>${row.state}</small></a>`:`<div class="production-slot empty"><strong>${slot}</strong><small>未完成 / 待资料</small></div>`}).join('')}</div>${productionTemplateButtons(p)}${target==='DRAFT'?`<div class="production-actions"><button class="button" data-action="flow-skill-prepare" data-id="${esc(p.id)}" ${viewer||active||!visual?'disabled':''}>原Skill上品预检</button><button class="button" data-action="flow-listing-browser" data-id="${esc(p.id)}" ${viewer?'disabled':''}>打开上品浏览器</button><button class="button" data-action="flow-listing-browser-status" data-id="${esc(p.id)}" ${viewer?'disabled':''}>检查上品连接</button><small>复用原Skill方案与已有图片，核对内容及征品属性、必要类目替换；后续由原脚本打开后台自动填写，原上传脚本使用本地图片。预检结果不代表草稿已保存。</small></div>${productionBrowserNote()}${productionListingSkillResult(p)}`:''}${p.draft?productionReceipt(p):''}<details class="production-details"><summary>模板与执行说明</summary><p>原 b2b-image-skill · 新版6主图＋12详情（m6合并Supplement Facts）；原 alibaba-attribute-filler · 原类目配置及字段定位。主图与详情的版式沿用原模板，最终成品位置仍需核验。旧版m7仅在历史任务中保留参数图区映射。当前通道：${esc(flow.imageProvider||'启动时确认')}。</p></details></section>`;
}
function productionReceipt(p){const draft=p.draft;return `<section class="production-receipt"><h3>草稿待用户检查</h3>${p.workflow?.listingMechanism==='original-skill-v1'?`<button class="button" data-action="flow-listing-complete" data-id="${esc(p.id)}" ${productionViewer()?'disabled':''}>补全原Skill属性与FAQ并保存原草稿</button><p>${draft.content_readback_verified===true?`完整内容已回读：普通属性 ${Object.keys(draft.fields||{}).length} 项 · 自定义属性 ${draft.content_coverage?.customAttributes||0}/10 · FAQ ${draft.content_coverage?.faqs||0}/8 · 卖点 ${draft.content_coverage?.sellingPoints||0}/5`:'完整内容覆盖尚未验收；历史非空字段回读不代表所有属性已填完。'}</p>`:''}<p>请打开后台核对完整草稿，确认无误后自行点击发布；工作台不代为发布。</p><p>${draft.readback_verified?(draft.image_review_required===true?'草稿已保存，原Skill字段回读通过；图片分区/顺序待后台终检':'已完成实际回读'):'保存或回读结果待核对，不自动重复创建'} · 草稿 ${esc(draft.draft_id||'编号待核对')}</p>${productionPublication(p)}${draft.draft_url?`<a class="button" href="${esc(safeReference(draft.draft_url))}" target="_blank" rel="noopener">打开后台草稿 ↗</a>`:''}<div class="table-scroll"><table><thead><tr><th>字段</th><th>预期</th><th>实际回读</th><th>结果</th></tr></thead><tbody>${Object.entries(draft.fields||{}).map(([key,row])=>`<tr><td>${esc(key)}</td><td>${esc(Array.isArray(row.expected)?row.expected.join('; '):row.expected)}</td><td>${esc(row.actual)}</td><td>${row.matched?'一致':'待整改'}</td></tr>`).join('')||'<tr><td colspan="4">尚无完整字段回读，不以保存动作代替核验。</td></tr>'}</tbody></table></div></section>`}
function productionStoreSelect(){return `<label>本批次目标店铺<select id="productionStore"><option value="">请选择目标店铺</option>${(executionData?.stores||[]).map(s=>`<option value="${esc(s.id)}" ${productionStore===s.id?'selected':''}>${esc(s.label)}</option>`).join('')}</select></label>`}
function productionWorkspace(kind){
 const listing=kind==='listing';
 const ps=executionData?.products||[];
 return head(listing?'上品管理':'视觉生图',listing?'新品属性方案、类目定位、草稿保存和回读共用同一主任务。':'新品、选品和征品参考共用原Skill新品流程及固定模板。','PRODUCT PRODUCTION',false)+`<p class="execution-note">原 Skill 优先生成产品资料并复用已有方案、当前版本图片，无需先手填全部资料。新任务仅确认正式首图 m1，随后按原 Skill 推进套图与草稿；异常由系统列明，不重复追问已确认内容。未核实事实保留待核验，最终由你检查后台草稿并自行发布。当前在本机执行，服务器后续再接。</p><div class="production-workspace-toolbar"><button class="button primary" data-action="flow-new" ${productionViewer()?'disabled':''}>建立新品需求</button>${productionStoreSelect()}<span>${listing?'当前图片 → 草稿预检 · 自行后台发布':'仅图片完成后停止 · 需要时到上品管理生成草稿'}</span></div>${ps.map(p=>`<details class="panel production-item" ${ps.length===1?'open':''}><summary><strong>${esc(p.title)}</strong><span>${esc(productionSource(p))} · ${esc(productionStates[p.workflow?.status]||'未启动')} · V${p.revision}</span></summary><p><a class="button" href="${executionURL(p.id)}">资料 / 匹配 / 审核 ↗</a></p>${productionPanel(p,listing?'DRAFT':'VISUALS')}</details>`).join('')||'<section class="panel production-panel"><p>先建立新品需求，或从选品、征品中勾选参考产品。</p></section>'}`;
}
async function productionPreview(items,key,target='DRAFT',approvalPolicy=productionHeroPolicy){
 const plan=await executionCommand({action:'workflow.preview',items,store:key||undefined,target,approvalPolicy});
 productionBatch={items:plan.items.filter(p=>p.eligible).map(p=>({id:p.id,revision:p.revision})),store:key,target,approvalPolicy};
 openDrawer(`<h2 id="drawerTitle">一键制作 · 执行预检</h2><p>${approvalPolicy===productionHeroPolicy?(target==='VISUALS'?'先生成正式首图m1，查看并确认一次后制作完整套图及质检，仅图片完成后停止，不保存草稿。':'先生成正式首图m1，查看实际首图并确认一次后，自动制作完整套图、质检和保存后台草稿；最后请自行检查并在后台发布。'):target==='VISUALS'?'先准备同源新品属性方案，再生成包装和固定套图；包装、图片等待人工审核，仅图片完成后停止，不自动上品或报名。':'同一任务连续完成新品包装、固定套图、属性方案及后台草稿。包装、图片和属性等待你审核后自动接续。'}本次仅使用已有执行方式与额度。</p>${plan.items.map(p=>`<section class="production-plan-row"><strong>${esc(p.title)} · V${p.revision}</strong><p>${esc(p.message)}</p>${p.gaps?.length?`<p>需处理：${esc(p.gaps.join('、'))}</p>`:''}</section>`).join('')}<button class="button primary" data-action="flow-start" ${plan.eligible?'':'disabled'}>确认本批次额度并启动${target==='VISUALS'?'仅图片制作':'至草稿'}</button>`);
}
function productionProposal(p){
 const plan=p.attributePlan,viewer=productionViewer();
 openDrawer(`<h2 id="drawerTitle">新品属性方案 · V${p.revision}</h2><p>原 Skill 优先生成并复用属性方案，此处用于查看或修改，无需为启动逐项手填。方案保留参考、拟采用和已确认的来源区别；未核实资料不会自动成为本品事实。</p><form id="productionAttributeForm" data-id="${esc(p.id)}" data-revision="${p.revision}" data-job="${esc(plan.job)}" data-fingerprint="${esc(plan.fingerprint)}"><div class="production-attribute-fields">${Object.entries(plan.manifest.fields||{}).map(([key,value])=>{const source=plan.field_sources['fields.'+key]||{};return `<label>${esc(key)}<input data-plan-field="${esc(key)}" data-value-type="${Array.isArray(value)?'array':'string'}" value="${esc(Array.isArray(value)?value.join('; '):value)}" ${viewer?'readonly':''}><small>${esc(({REFERENCE:'参考来源',DESIGN:'拟采用方案',CONFIRMED:'确认资料'})[source.kind]||'来源待补')}：${esc(source.source||'请补充来源')}</small></label>`}).join('')}</div><details><summary>完整属性、价格及FAQ方案（可编辑原Skill格式）</summary><textarea id="productionManifest" rows="16" ${viewer?'readonly':''}>${esc(JSON.stringify(plan.manifest,null,2))}</textarea></details><label>仍需解决的问题（一行一项，解决后清除）<textarea id="productionUnresolved" rows="4" ${viewer?'readonly':''}>${esc((plan.unresolved||[]).join('\n'))}</textarea></label><label><input type="checkbox" id="productionPlanAcknowledged" ${viewer?'disabled':''}> 我已核对拟采用参数、来源及供货条件，确认可用于本次新品草稿。</label><div class="production-actions"><button class="button" type="submit" name="intent" value="save" ${viewer?'disabled':''}>保存方案，暂不确认</button><button class="button primary" type="submit" name="intent" value="approve" ${viewer?'disabled':''}>确认属性，继续原Skill上品</button></div></form>`);
}

const productionOldProductPage=workproductPage;
workproductPage=function(){
 const html=productionOldProductPage();
 const id=new URLSearchParams(location.hash.split('?')[1]||'').get('item');
 const p=productionProduct(id);if(!p)return html;
 const original=/<section class="panel execution-form-panel"><h2>执行与审核<\/h2>[\s\S]*?<\/section>/;
 return original.test(html)?html.replace(original,productionPanel(p)):html+productionPanel(p);
};
const productionOldModulePage=modulePage;
modulePage=function(id){return ['images','listing'].includes(id)?productionWorkspace(id):productionOldModulePage(id)};
const productionOldSelectionPage=selectionPage;
selectionPage=function(){return productionOldSelectionPage().replace('<div class="selection-tabs">',`<div class="production-selection-store">${productionStoreSelect()}<p>勾选后进入同一新品主任务；已有部分图片和待审核成果会复用。</p></div><div class="selection-tabs">`)};
hubPreviewProducts=async function(items){await productionPreview(items,typeof topicStore==='undefined'?undefined:topicStore)};

document.addEventListener('change',event=>{if(event.target.id==='productionStore')productionStore=event.target.value});
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-action]');if(!button)return;
 const action=button.dataset.action;
 const intercepted=['selection-batch-preview','recruit-image-preview','recruit-image-one','execution-approve','execution-new'];
 if(!action.startsWith('flow-')&&!intercepted.includes(action))return;
 event.preventDefault();event.stopImmediatePropagation();
 try{
  if(productionViewer()&&action!=='flow-template')throw Error('当前为只读查看，请由本机管理员执行');
  const p=productionProduct(button.dataset.id);
  if(action==='flow-preview'){
   if(productionResumeJob(p))throw Error('已有当前版本原生图片任务，请恢复原任务与缓存，不重新生成');
   if(typeof executionDirty!=='undefined'&&executionDirty)throw Error('请先保存产品资料，再预检制作');
   let target=p;
   if(!p.facts.store&&productionStore)target=await executionCommand({action:'product.save',id:p.id,revision:p.revision,facts:{...p.facts,store:productionStore}});
   await productionPreview([{id:target.id,revision:target.revision}],target.facts.store,button.dataset.target||'DRAFT',productionPolicy(p)||null);
  }
  if(action==='flow-start'){
   if(!productionBatch?.items.length)throw Error('请先完成本批次预检');
   if(productionBatch.items.some(item=>productionResumeJob(productionProduct(item.id))))throw Error('已有当前版本原生图片任务，请恢复原任务与缓存，不重新生成');
   button.disabled=true;
   const result=await executionCommand({action:'workflow.start',...productionBatch,acknowledgeExecution:true,imageProvider:'codex-native'});
   const visualOnly=productionBatch.target==='VISUALS';productionBatch=null;closeDrawer();render();toast(`已建立 ${result.started.length} 个主任务，${visualOnly?'图片审核后停止，不自动上品':'审核后自动接续'}`);
  }
  if(action==='flow-stop'){await executionCommand({action:'workflow.stop',id:p.id});render();toast('已停止后续交接，当前产物保留')}
  if(action==='flow-hero-review'){
   if(!productionHeroCurrent(p))throw Error('首图资料已变化或尚未通过模板核验，请处理后重新生成首图');
   const hero=p.hero,row=hero.images.find(row=>row.slot==='m1'),visualOnly=p.workflow?.target==='VISUALS';
   openDrawer(`<h2 id="drawerTitle">查看实际首图 m1</h2><p>${esc(p.title)} · V${p.revision} · ${esc(hero.job)}</p><a href="${productionAssetURL(hero,row)}" target="_blank" rel="noopener"><img src="${productionAssetURL(hero,row)}" style="width:100%" alt="当前固定模板首图 m1"></a><p>${visualOnly?'确认此首图后，自动完成其余图片和质检；仅图片完成后停止，需要草稿时再到上品管理预检。':'确认此首图后，自动完成其余图片、质检、属性填写及后台草稿回读；最终由你检查草稿并在后台自行发布。'}</p><form id="productionHeroReview" data-id="${esc(p.id)}" data-revision="${p.revision}" data-job="${esc(hero.job)}" data-fingerprint="${esc(hero.attributePlanFingerprint)}" data-pixel-hash="${esc(hero.pixelHash)}"><label><input name="acknowledgeHero" type="checkbox" required>我已查看实际首图、核对本次属性方案，确认按此方向${visualOnly?'完成本次仅图片制作':'自动制作到草稿'}。</label><button class="button primary">${visualOnly?'确认首图并制作完整套图':'确认首图并自动制作到草稿'}</button></form>`);
  }
  if(action==='flow-listing-complete'){button.disabled=true;await executionCommand({action:'listing.skill.complete',id:p.id,revision:p.revision});render();toast('已按原Skill补全同一草稿并回读，图片沿用；未发布')}
  if(action==='flow-skill-prepare'){button.disabled=true;await executionCommand({action:'listing.skill.prepare',id:p.id,revision:p.revision});render();[...document.querySelectorAll('[data-action="flow-skill-prepare"]')].find(item=>item.dataset.id===p.id)?.closest('details')?.setAttribute('open','');toast('原Skill内容预检与字段替换结果已回填；草稿保存以实际回读为准')}
  if(action==='flow-listing-browser'){button.disabled=true;const result=await executionCommand({action:'listing.browser.open',id:p.id,revision:p.revision});openDrawer(`<h2 id="drawerTitle">原Skill上品浏览器</h2><p>目标店铺：${esc((executionData.stores||[]).find(row=>row.id===p.facts.store)?.label||p.facts.store||'未指定')}</p><p>${esc(result.message)}</p><p>回到工作台后继续至草稿；实际账号、填写、上传和保存仍由原脚本核验。</p>`);button.disabled=false}
  if(action==='flow-listing-browser-status'){
   button.disabled=true;
   try{productionBrowserStatus=await executionCommand({action:'listing.browser.status'});render();toast(productionBrowserStatus.message||'已检查上品连接')}
   finally{button.disabled=false}
  }
  if(action==='flow-publication-refresh'){button.disabled=true;try{await executionCommand({action:'publication.refresh',id:p.id,recoverBrowser:true});render();toast('已读取商品管理页状态；无法核实的状态保留未知')}finally{button.disabled=false}}
  if(action==='flow-template'){
   const template=p.templatePreviews?.find(row=>row.slot===button.dataset.slot),output=productionOutputs(p).get(button.dataset.slot);
   if(!template||!output)throw Error('此模块没有原版本底图可对照');
   openDrawer(`<h2 id="drawerTitle">${esc(output.slot)} · 原模板与成品位置对照</h2><p>核对标题、Logo、卖点和产品位置；底图含占位产品，成品由原Skill裁切归一。此预览不代表位置检查自动通过。</p><figure><figcaption>原Skill换图底图</figcaption><img src="${esc(template.url)}" style="width:100%" alt="原固定底图"></figure><figure><figcaption>当前已生成成品 · ${esc(output.state)}</figcaption><img src="${productionAssetURL(output,output)}" style="width:100%" alt="当前成品"></figure>`);
  }
  if(action==='flow-reconcile'){await executionCommand({action:'job.reconcile-output',id:button.dataset.job,refreshSavedDraft:Boolean(p.draft?.draft_id)});render();toast('已核对已有结果，未重复生图或保存草稿')}
  if(action==='flow-attributes'){
   if(p.attributePlan?.revision===p.revision)productionProposal(p);
   else openDrawer(`<h2 id="drawerTitle">准备新品属性方案</h2><p>使用原上品Skill分析参考及新品需求，只准备属性和来源，不连接平台。将使用已有模型额度。</p><button class="button primary" data-action="flow-prepare-attributes" data-id="${esc(p.id)}">确认额度并准备方案</button>`);
  }
  if(action==='flow-prepare-attributes'){
   await executionCommand({action:'product.run',id:p.id,revision:p.revision,kind:'attributes',acknowledgeExecution:true});closeDrawer();render();toast('属性方案已排队，完成后可查看并确认');
  }
  if(action==='flow-native'){
   openDrawer(`<h2 id="drawerTitle">恢复原生固定模板任务</h2><p>复用当前任务的模板和缓存，只继续未完成部分，使用已有额度。</p><button class="button primary" data-action="flow-native-confirm" data-id="${esc(p.id)}" data-job="${esc(button.dataset.job)}">确认继续原任务</button>`);
  }
  if(action==='flow-native-confirm'){
   await executionCommand({action:'job.resume-native',id:button.dataset.job,revision:p.revision,acknowledgeExecution:true});
   await executionCommand({action:'workflow.start',items:[{id:p.id,revision:p.revision}],store:p.facts.store,target:p.workflow?.target||'DRAFT',approvalPolicy:productionPolicy(p)||null,acknowledgeExecution:true});closeDrawer();render();
  }
  if(action==='selection-batch-preview'||action==='recruit-image-preview'||action==='recruit-image-one'){
   const recruitment=action!=='selection-batch-preview',single=action==='recruit-image-one';
   if(recruitment&&recruitLoading)throw Error('征品列表正在加载，请稍候');
   const key=recruitment?topicStore:productionStore;
   if(!key)throw Error('请先选择本批次目标店铺');
   const ids=single?[button.dataset.id]:recruitment?[...recruitImageSelected]:[...selectedCandidates];
   const adopted=await executionCommand({action:'workflow.adopt',source:recruitment?'recruitment':'selection',ids,store:key,businessType:recruitment?recruitType:undefined,target:'DRAFT',approvalPolicy:productionHeroPolicy});
   await productionPreview(adopted.items,key,'DRAFT',productionHeroPolicy);
  }
  if(action==='execution-approve'){
   const phase=button.dataset.phase,asset=phase==='packaging'?p.packaging:p.visual;
   if(p.workflow?.approvalPolicy===productionHeroPolicy&&phase!=='draft')throw Error('本任务只需确认实际首图；后续资料或质检问题请按需处理提示修正');
   if(phase==='draft'){await executionCommand({action:'product.approve',id:p.id,revision:p.revision,phase});render();return}
   if(!asset||asset.revision!==p.revision)throw Error('没有可审核的当前产物');
   openDrawer(`<h2 id="drawerTitle">审核当前${phase==='packaging'?'包装':'套图'}</h2><p>${esc(p.title)} · V${p.revision} · 产物 ${esc(asset.job)}</p><form id="productionArtifactReview" data-id="${esc(p.id)}" data-phase="${phase}" data-revision="${p.revision}" data-job="${esc(asset.job)}"><label><input type="checkbox" required>我已查看此产物，核对包装、规格、文案及模板位置，确认可交接。</label>${phase==='visual'?'<p>待人工规格核对；旧资产缺少当前规格回执时仍需核对，不能由文件存在自动放行。</p><label><input name="specificationReviewed" type="checkbox" required>我已对照本次属性方案及模板，逐项核对成品规格。</label>':''}${p.recruitment&&phase==='visual'?'<label><input name="topicImageReviewed" type="checkbox" required>我已对照主题参考图核对当前首图主体。</label>':''}<button class="button primary">确认此产物并继续</button></form>`);
  }
  if(action==='flow-new'||action==='execution-new'){
   openDrawer(`<h2 id="drawerTitle">建立新品需求</h2><form id="productionNewReference"><label>新品名称<input name="title" required maxlength="200"></label><label>剂型<input name="form" required placeholder="例如 Powder / Gummy / Oral Liquid"></label><label>包装与设计需求<textarea name="design" required rows="5" placeholder="包装形态、目标买家、配色与准确印字；也可填写参考来源"></textarea></label>${productionStoreSelect()}<button class="button primary">建立新品档案</button></form>`);
  }
 }catch(error){toast(error.message||'操作未完成');button.disabled=false}
},true);

document.addEventListener('submit',async event=>{
 const form=event.target;if(!['productionAttributeForm','productionArtifactReview','productionNewReference','productionHeroReview'].includes(form.id))return;
 event.preventDefault();event.stopImmediatePropagation();
 try{
  if(productionViewer())throw Error('当前为只读查看');
  if(form.id==='productionHeroReview'){
   const data=Object.fromEntries(new FormData(form));if(data.acknowledgeHero!=='on')throw Error('请先勾选确认已查看实际首图');
   await executionCommand({action:'hero.approve',id:form.dataset.id,revision:Number(form.dataset.revision),artifactJob:form.dataset.job,fingerprint:form.dataset.fingerprint,pixelHash:form.dataset.pixelHash,acknowledgeHero:true});closeDrawer();render();toast(productionProduct(form.dataset.id)?.workflow?.target==='VISUALS'?'首图已确认，完成套图后停止，不保存草稿':'首图已确认，自动制作到草稿；遇到资料或质检问题将提示处理');return;
  }
  if(form.id==='productionNewReference'){
   const data=Object.fromEntries(new FormData(form));
   const p=await executionCommand({action:'product.create',...data,store:productionStore});closeDrawer();location.hash=executionURL(p.id);return;
  }
  if(form.id==='productionArtifactReview'){
   const data=Object.fromEntries(new FormData(form));
   if(form.dataset.phase==='visual'&&data.specificationReviewed!=='on')throw Error('请先勾选确认已人工核对成品规格');
   await executionCommand({action:'product.approve',id:form.dataset.id,revision:Number(form.dataset.revision),phase:form.dataset.phase,artifactJob:form.dataset.job,topicImageReviewed:data.topicImageReviewed==='on',specificationReviewed:data.specificationReviewed==='on'});closeDrawer();render();return;
  }
  if(event.submitter?.value==='approve'&&!document.getElementById('productionPlanAcknowledged').checked)throw Error('请先勾选确认新品参数及来源');
  const p=productionProduct(form.dataset.id),plan=p.attributePlan;
  let manifest=JSON.parse(document.getElementById('productionManifest').value);
  const sources=JSON.parse(JSON.stringify(plan.field_sources));
  for(const input of form.querySelectorAll('[data-plan-field]')){
   const key=input.dataset.planField,prior=plan.manifest.fields[key];
   const value=input.dataset.valueType==='array'?input.value.split(';').map(s=>s.trim()).filter(Boolean):input.value;
   if(JSON.stringify(value)!==JSON.stringify(prior)){
    manifest.fields[key]=value;sources['fields.'+key]={kind:'DESIGN',source:'用户在工作台修改并拟采用的新品参数'};
   }
  }
  const unresolved=document.getElementById('productionUnresolved').value.split('\n').map(s=>s.trim()).filter(Boolean);
  const edited=await executionCommand({action:'attributes.edit',id:p.id,revision:p.revision,manifest,field_sources:sources,unresolved,fingerprint:form.dataset.fingerprint});
  form.dataset.fingerprint=edited.attributePlan.fingerprint;form.dataset.job=edited.attributePlan.job;
  p.attributePlan=edited.attributePlan;
  if(event.submitter?.value==='approve'){
   await executionCommand({action:'attributes.approve',id:p.id,revision:p.revision,job:edited.attributePlan.job,fingerprint:edited.attributePlan.fingerprint,acknowledgeSpecifications:true});
  }
  closeDrawer();render();toast('属性方案已保存，主任务按审核状态继续');
 }catch(error){toast(error.message||'方案未保存')}
},true);
if(typeof render==='function')render();
