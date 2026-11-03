'use strict';
let rectificationOnlyIssues=false;
let rectificationDetectBusy=false;
const rectificationLabels={MATCHED:'本地对照一致',MISMATCH:'需要整改',TO_CONFIRM:'待补资料',MANUAL:'你手动绑定'};
const rectificationBasePage=workproductPage;
function rectificationCanDetect(p){
 const d=p.draft||{};
 return d.readback_verified===true&&d.revision===p.revision&&d.store===p.facts?.store&&d.store===p.recruitment?.store&&Boolean(d.draft_id&&p.recruitment?.topicId);
}
function rectificationPlatformPanel(p){
 const state=p.rectification.platform||{},items=state.items||[],viewer=typeof teamViewOnly==='function'&&teamViewOnly();
 const labels={NOT_RUN:'尚未检测',STALE:'检测结果需更新',PASSED:'已检测 · 符合要求',FAILED:'已检测 · 未符合要求'};
 return `<section class="production-message"><strong>平台征品检测：${esc(labels[state.status]||'尚未检测')}</strong><p>读取当前已保存草稿的主题资格；不报名或发布。</p>${state.checkedAt?`<small>检测时间：${esc(integrationDate(state.checkedAt))}</small>`:''}${state.message?`<p>${esc(state.message)}</p>`:''}${items.length?`<div class="table-scroll"><table><thead><tr><th>检测项</th><th>平台要求</th><th>检测结果</th></tr></thead><tbody>${items.map(row=>`<tr><td>${esc(row.itemName||row.itemCode)}</td><td>${esc((row.itemValue||[]).join(' / '))}</td><td>${row.meet?'通过':'未符合'}${Number.isFinite(row.score)?' · 图片匹配得分 '+esc(row.score):''}</td></tr>`).join('')}</tbody></table></div>`:''}<button class="button" data-action="rectification-detect" data-id="${esc(p.id)}" ${viewer||rectificationDetectBusy||!rectificationCanDetect(p)?'disabled':''} aria-busy="${rectificationDetectBusy?'true':'false'}">${rectificationDetectBusy?'检测中…':'检测当前草稿'}</button>${!rectificationCanDetect(p)?'<small>需要同版本、同店铺且已实际回读通过的草稿。</small>':''}</section>`;
}
workproductPage=function(){
  const html=rectificationBasePage(),p=executionProduct();
  if(!p?.rectification)return html;
  const marker='<section class="panel execution-form-panel">';
  return html.replace(marker,rectificationPanel(p)+marker);
};
function rectificationPanel(p){
  const r=p.rectification,rows=r.rows;
  const mismatch=r.rows.filter(x=>x.status==='MISMATCH').length,pending=r.rows.filter(x=>x.status==='TO_CONFIRM').length;
  const expected=row=>row.expected.filter(Boolean).join(' / ')||'平台未返回完整值';
  return `<section class="rectification-panel" id="rectificationPanel">
    <div class="rectification-heading"><div><span class="eyebrow">REQUIREMENTS → FACTS → DRAFT → PLATFORM CHECK</span><h2>征品整改工作区</h2><p>主题 ${esc(r.topicId)} · ${esc(r.store)} · ${r.businessType==='HOT_PRODUCT'?'交易品定招':'商机品定招'} · 资料 V${p.revision}</p></div><a class="button" href="#demands">返回征品列表 ↗</a></div>
    <div class="rectification-summary"><div><strong>${r.matchedCount}</strong><span>本地对照一致</span></div><div class="issue"><strong>${mismatch}</strong><span>需要整改</span></div><div><strong>${pending}</strong><span>待补资料</span></div><div><strong>${r.manualCount}</strong><span>证书人工待办</span></div></div>
    <div class="rectification-source">${safeReference(r.referenceImage)?`<img src="${esc(safeReference(r.referenceImage))}" alt="征品主题参考图" referrerpolicy="no-referrer">`:''}<div><strong>${esc(r.topicTitle)}</strong><p>主题图用于匹配主体与包装方向；我方实际属性和资料依据须独立确认。证书由你后续在后台绑定，内部整改和草稿准备可以继续。</p><small>要求快照 ${esc(integrationDate(r.captured))} · ${esc(r.fingerprint.slice(0,12))}</small></div></div>
    <div class="rectification-toolbar"><label><input id="rectificationOnlyIssues" type="checkbox" ${rectificationOnlyIssues?'checked':''}>仅看待处理项</label><button class="button" type="button" data-action="rectification-export" data-id="${esc(p.id)}">导出整改清单</button></div>
    <form id="rectificationForm" data-id="${esc(p.id)}" data-revision="${p.revision}"><div class="rectification-table-wrap"><table class="rectification-table"><thead><tr><th>检查项目 / 平台字段</th><th>征品要求</th><th>我方实际值与依据</th><th>草稿实际值</th><th>整改状态与处理建议</th></tr></thead><tbody>
    ${rows.map((row,index)=>`<tr class="rectification-row ${row.status.toLowerCase()}" data-rule-key="${esc(row.key)}" ${rectificationOnlyIssues&&row.status==='MATCHED'?'hidden':''}><td><strong>${esc(row.name)}</strong>${row.fieldId?`<small>字段 ID ${esc(row.fieldId)}</small>`:''}<small>${esc(row.description||'')}</small></td><td><span class="rectification-required">${esc(expected(row))}</span>${row.options?.length?`<small>${row.options.map(o=>esc(o.name)+' · '+esc(o.id||'选项ID未返回')).join('<br>')}</small>`:''}</td><td>${row.kind==='manual'?'<div class="rectification-manual">由你后续在后台绑定<br><small>此处不记录为已关联</small></div>':`<label class="sr-label" for="rect-actual-${index}">${esc(row.name)}：我方实际值</label>${row.kind==='image'?`<select id="rect-actual-${index}" data-rect-field="actual"><option value="">请选择实际核对结果</option>${['主体相似','需要整改'].map(x=>`<option ${row.actual===x?'selected':''}>${x}</option>`).join('')}</select>`:`<input id="rect-actual-${index}" data-rect-field="actual" value="${esc(row.actual)}" maxlength="2000" list="rect-options-${index}" placeholder="填写真实值，不自动套用要求"><datalist id="rect-options-${index}">${row.expected.filter(Boolean).map(x=>`<option value="${esc(x)}"></option>`).join('')}</datalist>`}<label class="sr-label" for="rect-evidence-${index}">${esc(row.name)}：资料依据</label><input id="rect-evidence-${index}" data-rect-field="evidence" value="${esc(row.evidence)}" maxlength="2000" placeholder="资料依据：规格表、配方或后台记录"><label class="sr-label" for="rect-note-${index}">${esc(row.name)}：整改备注</label><textarea id="rect-note-${index}" data-rect-field="note" rows="2" maxlength="2000" placeholder="整改说明 / 待确认事项">${esc(row.note)}</textarea>`}</td><td><span class="rectification-readback">${esc(row.draftActual)}</span><small>后台草稿保存并实际回读后核对</small></td><td><span class="rectification-status ${row.status.toLowerCase()}">${rectificationLabels[row.status]}</span><p>${esc(row.message)}</p><small>${esc(row.fix)}</small></td></tr>`).join('')||'<tr><td colspan="5">当前筛选没有待处理项。</td></tr>'}</tbody></table></div><div class="rectification-footer"><button class="button primary" type="submit">保存整改并重新对照</button><span>填写要求值不会直接更改后台；本地一致不等于平台征品通过。</span></div></form>
    ${r.blockers.includes('目标店铺与征品来源店铺不一致')?'<p class="rectification-warning">上品店铺与征品来源不一致，请先改正目标店铺。</p>':''}
    <div class="rectification-next"><div><strong>${r.readyForDraft?'本地整改已就绪，待核对上品资料与图片':'本地供货资料与草稿值分别保留，平台结论见下方检测'}</strong><p>证书人工绑定 → 平台检测 → 你确认发布 → 回读发布及征品结果</p></div></div>${rectificationPlatformPanel(p)}
  </section>`;
}
function rectificationDownload(p){
  const r=p.rectification,lines=['检查项目','征品要求','我方实际值','资料依据','草稿实际值','状态','整改说明','处理建议'];
  const quote=x=>{let text=String(x??'');if(/^[\s]*[=+@-]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
  const csv=[lines,...r.rows.map(x=>[x.name,x.expected.join(' / '),x.actual,x.evidence,x.draftActual,rectificationLabels[x.status],x.note,x.fix])].map(row=>row.map(quote).join(',')).join('\r\n');
  const blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=`征品整改_${r.store}_${r.topicId}_V${p.revision}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function rectificationAdopt(id){
  const p=await executionCommand({action:'topic.adopt',store:topicStore,topic:id,businessType:recruitType});
  closeDrawer();location.hash=executionURL(p.id);render();
  return p;
}
candidateFromTopic=async function(id){try{await rectificationAdopt(id);toast('主题要求已带入征品整改表，证书由你后续绑定')}catch(error){toast(error.message||'征品交接失败')}};
document.addEventListener('click',async e=>{
  const el=e.target.closest('[data-action]');if(!el)return;
  if(el.dataset.action==='rectification-detect'){
    e.preventDefault();
    if(typeof teamViewOnly==='function'&&teamViewOnly()){toast('当前为只读查看，请由本机管理员检测');return}
    const p=executionData?.products?.find(row=>row.id===el.dataset.id);
    if(rectificationDetectBusy||!p||!rectificationCanDetect(p)){toast('需要同版本、同店铺且回读通过的草稿');return}
    rectificationDetectBusy=true;el.disabled=true;el.setAttribute?.('aria-busy','true');
    try{const result=await executionCommand({action:'recruitment.detect',id:p.id,revision:p.revision});toast(result.platformDetection?.meet?'平台检测完成：符合要求；未报名或发布':'平台检测完成：存在未满足项，详见逐项结果')}
    catch(error){toast(error.message||'平台检测失败，未将其标记为通过')}
    finally{rectificationDetectBusy=false;render()}
  }
  if(el.dataset.action==='topic-start'||el.dataset.action==='topic-rectify'){
    el.disabled=true;
    try{await rectificationAdopt(el.dataset.id);toast(el.dataset.action==='topic-start'?'已建立生图任务资料包；先确认我方资料，再调用生图 Skill':'已打开当前主题整改记录')}
    catch(error){toast(error.message||'征品任务未创建');el.disabled=false}
  }
  if(el.dataset.action==='rectification-export'){
    const p=executionData?.products?.find(p=>p.id===el.dataset.id);if(p?.rectification)rectificationDownload(p);
  }
});
document.addEventListener('change',e=>{if(e.target.id==='rectificationOnlyIssues'){rectificationOnlyIssues=e.target.checked;document.querySelectorAll('.rectification-row.matched').forEach(row=>row.hidden=rectificationOnlyIssues)}});
document.addEventListener('submit',async e=>{
  const form=e.target;if(form.id!=='rectificationForm')return;e.preventDefault();
  const entries={};form.querySelectorAll('[data-rule-key]').forEach(row=>{
    if(!row.querySelector('[data-rect-field]'))return;
    entries[row.dataset.ruleKey]=Object.fromEntries([...row.querySelectorAll('[data-rect-field]')].map(input=>[input.dataset.rectField,input.value]));
  });
  const button=form.querySelector('[type=submit]');button.disabled=true;
  try{await executionCommand({action:'topic.rectify',id:form.dataset.id,revision:Number(form.dataset.revision),entries});render();toast('整改已保存并重新对照；未修改后台，证书仍由你绑定')}
  catch(error){toast(error.message||'整改保存失败');button.disabled=false}
});
