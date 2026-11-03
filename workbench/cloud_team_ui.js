'use strict';
let cloudTeamRequests=[],cloudTeamMessage='尚未同步云端任务申请';
const cloudOldTasksPage=tasksPage;
function cloudTeamPanel(){
 if(typeof teamViewOnly==='function'&&teamViewOnly())return '';
 const labels={RECEIVED_LOCAL:'待管理员确认',ADOPTED_LOCAL:'已接纳至产品预检',REJECTED:'已拒绝'};
 return `<section class="hub-panel" style="margin-top:24px"><div class="hub-panel-heading"><div><h2>外部团队任务申请</h2><p>公开入口仅提交申请；接纳后仍需你确认额度和阶段审核，才执行原Skill。</p><small>${esc(cloudTeamMessage)}</small></div><button class="button" data-action="cloud-sync">同步云端申请</button></div>${cloudTeamRequests.length?cloudTeamRequests.map(r=>`<article class="hub-existing" style="display:block;margin:12px 0"><strong>${r.taskType==='images'?'包装与套图申请':'选品研究申请'} · ${esc(r.store)}</strong><p>${r.selected.length} 个参考产品 · ${esc(labels[r.status]||r.status)} · ${esc(r.createdAt)}</p><p style="white-space:pre-wrap">外部备注（需自行核验）：${esc(r.note)}</p><small>编号 ${esc(r.id)}</small>${r.status==='RECEIVED_LOCAL'?`<div class="hub-card-actions"><button class="button primary" data-action="cloud-adopt" data-id="${esc(r.id)}">接纳并预检</button><button class="button" data-action="cloud-reject" data-id="${esc(r.id)}">拒绝申请</button></div>`:''}${(r.items||[]).map(p=>`<a class="button" href="${executionURL(p.id)}">打开产品资料</a>`).join('')}</article>`).join(''):'<div class="hub-empty">目前没有外部任务申请。</div>'}</section>`;
}
tasksPage=function(){return cloudOldTasksPage()+cloudTeamPanel()};
async function cloudTeamLoad(){
 if(typeof teamViewOnly==='function'&&teamViewOnly())return;
 try{const r=await fetch('/api/cloud-team',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();cloudTeamRequests=d.requests||[];cloudTeamMessage=d.health?.status==='SUCCESS'?'已同步 · '+d.health.updatedAt:d.health?.message||'云端申请接收器已准备'}catch{cloudTeamMessage='云端申请暂未连接，原任务不受影响'}
 finally{if(current==='tasks'&&!document.body.classList.contains('modal-open'))render()}
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-action]');if(!button?.dataset.action.startsWith('cloud-'))return;
 event.preventDefault();event.stopImmediatePropagation();
 try{
  button.disabled=true;const action=button.dataset.action;
  if(action==='cloud-sync')await executionCommand({action:'cloud.sync'});
  else{const result=await executionCommand({action:action==='cloud-adopt'?'cloud.adopt':'cloud.reject',id:button.dataset.id});if(action==='cloud-adopt'){if(result.taskType==='images')await productionPreview(result.items,result.store);else if(result.items.length)location.hash=executionURL(result.items[0].id)}}
  await cloudTeamLoad();
 }catch(error){toast(error.message||'外部任务申请未处理')}
 finally{button.disabled=false}
},true);
setInterval(()=>{if(current==='tasks')cloudTeamLoad()},20000);
cloudTeamLoad();
