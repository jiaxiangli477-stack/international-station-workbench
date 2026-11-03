'use strict';
// Only the currently displayed dashboard frame (or explicitly opened connection window) can use this bridge.
function manualDashboardSource(event){
  const frame=document.getElementById('existingIntegrationFrame');
  if(frame && event.source===frame.contentWindow){
    const url=new URL(frame.src,location.href),match=/^\/shared\/([a-f0-9]{24})\/index\.html$/.exec(url.pathname);
    if(!match||event.origin!==url.origin)return null;
    return {snapshot:match[1],target:event.source,origin:event.origin};
  }
  if(location.pathname==='/dashboard-manual.html' && event.source===window.opener){
    const allowed='http://localhost:'+location.port,declared=new URLSearchParams(location.search).get('returnOrigin');
    if((declared!==allowed&&declared!=='null')||event.origin!==declared)return null;
    return {snapshot:new URLSearchParams(location.search).get('snapshot')||'',target:event.source,origin:event.origin};
  }
  return null;
}
window.addEventListener('message',async event=>{
  const data=event.data;
  if(!data||data.type!=='workbench-dashboard-manual'||typeof data.requestId!=='string'||data.requestId.length>100)return;
  const context=manualDashboardSource(event);if(!context)return;
  const payload={...data.payload,snapshot:context.snapshot};
  const reply={type:'workbench-dashboard-manual-result',requestId:data.requestId};
  try{
    let response;
    if(payload.action==='load'){
      const params=new URLSearchParams();for(const k of ['store','kind','start','end','snapshot'])params.set(k,payload[k]||'');
      response=await fetch('/api/dashboard/manual?'+params,{cache:'no-store'});
    }else response=await fetch('/api/dashboard/manual',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench':'1'},body:JSON.stringify(payload)});
    reply.data=await response.json();reply.ok=response.ok;reply.status=response.status;
    const status=document.getElementById('connectionStatus');if(status)status.textContent=response.ok?'已连接工作台；请保持此窗口打开。录入数据会按店铺和期间保存。':reply.data.error||'连接失败';
  }catch(error){reply.ok=false;reply.status=503;reply.data={error:'工作台未连接，录入仍在本机暂存，请导出备份。'};}
  // A file:// opener has an opaque origin; a wildcard is used only for this exact opener handle.
  context.target.postMessage(reply,context.origin==='null'?'*':context.origin);
});
if(location.pathname==='/dashboard-manual.html'&&window.opener){
  const origin=new URLSearchParams(location.search).get('returnOrigin');
  if(origin==='null'||origin==='http://localhost:'+location.port)window.opener.postMessage({type:'workbench-dashboard-manual-ready'},origin==='null'?'*':origin);
}
