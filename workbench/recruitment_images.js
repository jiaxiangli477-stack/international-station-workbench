'use strict';
let recruitImageSelected=new Set(),recruitImageScope='',recruitImagePending=null,recruitImageBusy=false;
const recruitImageBasePage=demandsPage;
function recruitImageReadonly(){return typeof teamViewOnly==='function'&&teamViewOnly()}
function recruitImageChecked(id){return recruitImageSelected.has(String(id))}
function refreshRecruitImageToolbar(){const bar=document.querySelector('.recruit-image-toolbar');if(bar)bar.outerHTML=recruitImageToolbar()}
function recruitImageToolbar(){const viewer=recruitImageReadonly();return `<div class="recruit-image-toolbar"><div><strong>勾选征品，批量生图</strong><small>${viewer?'当前为共享只读入口，请在本机管理员入口执行。':'主题参考图与属性要求作为概念设计任务书；无需先填真实配方、报价或证书。'}</small></div><div class="recruit-image-controls"><button class="button" data-action="recruit-image-select-page" ${viewer||recruitLoading?'disabled':''}>勾选本页（最多10项）</button><button class="button" data-action="recruit-image-clear">清空</button><button class="button primary" data-action="recruit-image-preview" ${viewer||!recruitImageSelected.size||recruitImageBusy||recruitLoading?'disabled':''}>${recruitImageBusy?'正在检查…':'已选 '+recruitImageSelected.size+' 项 · 生图'}</button></div></div>`}
demandsPage=function(){const scope=topicStore+':'+recruitType;if(recruitImageScope!==scope){recruitImageScope=scope;recruitImageSelected.clear();recruitImagePending=null}const html=recruitImageBasePage();return recruitHubTab==='topics'?html.replace('<div class="recruit-grid">',recruitImageToolbar()+'<div class="recruit-grid">'):html};
async function recruitImagePreview(){
  if(recruitImageReadonly())throw Error('当前是共享查看入口，请使用本机管理员入口生图');
  if(recruitLoading)throw Error('征品列表正在加载，请完成后再勾选生图');
  if(!recruitImageSelected.size)throw Error('请先勾选征品主题');
  const scope=topicStore+':'+recruitType;recruitImageBusy=true;render();
  try{
    const plan=await executionCommand({action:'topic.images.preview',store:topicStore,businessType:recruitType,topics:[...recruitImageSelected]});
    if(scope!==topicStore+':'+recruitType){toast('店铺或类型已切换，请重新预览');return}
    recruitImagePending=plan;
    const labels={market:'目标市场',form:'主题剂型未明确，请先在产品资料里指定设计剂型',design:'设计要求',own_image:'真实产品图'};
    openDrawer(`<h2 id="drawerTitle">征品勾选生图 · 执行预览</h2><p>${esc(plan.store)} · ${nativeTypes[plan.businessType]} · 本次 ${plan.items.length} 项，可执行 ${plan.eligible} 项。</p><p>使用已有生图 Skill 与服务额度；先生成包装方向，审核后制作7张主图和12个详情模块。不自动上品或报名。</p>${plan.items.map(item=>`<div class="selection-plan-row"><strong>${esc(item.title)}</strong><small>主题 ${esc(item.topic)} · ${esc(item.scope)}</small><p>${item.eligible?(item.kind==='packaging'?'生成概念包装方向，审核后继续整套图片':'使用已审核包装或真实产品图，生成整套主图与详情'):esc(item.gaps.map(x=>labels[x]||x).join('、'))}</p>${item.designForm?`<small>设计目标剂型：${esc(item.designForm)}（主题要求，非我方已确认属性）</small>`:''}${item.product?`<p><a href="${executionURL(item.product)}" data-action="close-drawer">查看原产品资料 / 审核 ↗</a></p>`:''}</div>`).join('')}<button class="button primary" data-action="recruit-image-start" ${plan.eligible?'':'disabled'}>确认使用已有额度并开始生图</button>`);
  }finally{recruitImageBusy=false;refreshRecruitImageToolbar()}
}
document.addEventListener('change',e=>{
  const id=e.target.dataset.recruitImage;if(!id)return;
  if(recruitImageReadonly()||recruitLoading){e.target.checked=recruitImageChecked(id);return}
  if(e.target.checked&&recruitImageSelected.size>=10){e.target.checked=false;toast('每批最多勾选10个主题');return}
  e.target.checked?recruitImageSelected.add(id):recruitImageSelected.delete(id);render();
});
document.addEventListener('click',async e=>{
  const el=e.target.closest('[data-action]');if(!el?.dataset.action.startsWith('recruit-image-'))return;const action=el.dataset.action;
  try{
    if(action==='recruit-image-clear'){recruitImageSelected.clear();render();return}
    if(recruitImageReadonly())throw Error('共享查看身份不能执行，请在本机管理员入口操作');
    if(action==='recruit-image-select-page'){if(recruitLoading)return;for(const row of topicData?.records||[]){if(recruitImageSelected.size<10)recruitImageSelected.add(String(row.id))}render()}
    if(action==='recruit-image-one'){if(recruitLoading)return;recruitImageSelected=new Set([el.dataset.id]);await recruitImagePreview()}
    if(action==='recruit-image-preview')await recruitImagePreview();
    if(action==='recruit-image-start'){
      const plan=recruitImagePending;if(!plan||plan.store!==topicStore||plan.businessType!==recruitType)throw Error('店铺、类型或预览已变化，请重新勾选');
      el.disabled=true;
      const result=await executionCommand({action:'topic.images.start',store:plan.store,businessType:plan.businessType,items:plan.items,acknowledgeExecution:true});
      recruitImagePending=null;closeDrawer();recruitHubTab='production';hubWriteRoute();render();
      toast(`已提交 ${result.started.length} 项征品生图任务${result.blocked.length?'，'+result.blocked.length+' 项需处理':''}，进度与预览在此查看`);
    }
    if(action==='recruit-image-stop'){await executionCommand({action:'topic.images.stop',id:el.dataset.id});render();toast('已停止后续生图交接，当前阶段产物保留待审核')}
  }catch(error){toast(error.message||'征品生图未提交');if(action==='recruit-image-start')el.disabled=false}
});
