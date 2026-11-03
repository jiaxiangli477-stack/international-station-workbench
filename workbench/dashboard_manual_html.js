/* DASHBOARD_MANUAL_HTML_V1: portable manual fields, scoped by store and period. */
(function(){
  if(window.__dashboardManualHTMLV1)return;
  window.__dashboardManualHTMLV1=true;
  var identity=String(D.meta.store_id||('name:'+String(D.meta.store_name||'').trim().toLowerCase()));
  var fields=['acquisition','quality_customers','cac','sample_orders','sample_products','order_products','annual_fee','wendin','topshow','brand_ad','ad_spend_override','new_count','new_selection'];
  var map={acq:'acquisition',qc:'quality_customers',cac:'cac',sample:'sample_orders',sampleprod:'sample_products',orderprod:'order_products',annual:'annual_fee',wendin:'wendin',topshow:'topshow',brand:'brand_ad',adov:'ad_spend_override',newcount:'new_count'};
  var memory=Object.create(null),embedded=Object.create(null),dirty=false,status='填写后请点击「保存数据到HTML」，以后打开保存后的文件。';
  var hasArchive=typeof MANUAL==='object'&&MANUAL!==null;
  function clone(x){return JSON.parse(JSON.stringify(x));}
  function clean(value){
    var out={};fields.forEach(function(k){
      if(!value||!Object.prototype.hasOwnProperty.call(value,k))return;
      var v=value[k];
      if(k==='new_selection'){if(Array.isArray(v))out[k]=v.filter(function(x){return typeof x==='string';}).slice();}
      else if(k==='sample_products'||k==='order_products'){if(typeof v==='string')out[k]=v;}
      else if(v===null||typeof v==='number'&&Number.isFinite(v)&&v>=0)out[k]=v;
    });return out;
  }
  function validKey(key){return /^(week|month):\d{4}-\d{2}-\d{2}$/.test(key)&&Object.prototype.hasOwnProperty.call(D.audit_periods||{},key);}
  function storageKey(key){return 'dashboard_manual_html_v1_'+encodeURIComponent(identity)+'_'+key;}
  function validRecord(r,key){return r&&r.store===identity&&r.period===key&&r.fields&&typeof r.fields==='object';}
  try{
    var node=document.getElementById('dashboard-manual-snapshot'),bundle=node&&JSON.parse(node.textContent);
    if(bundle&&bundle.format==='dashboard-manual-html/v1'&&bundle.store===identity)
      Object.keys(bundle.entries||{}).forEach(function(key){var r=bundle.entries[key];if(validKey(key)&&validRecord(r,key)&&(!hasArchive||!r.end||r.end===manualScope(key).end))embedded[key]={store:identity,period:key,end:r.end,baseRevision:Number.isInteger(r.baseRevision)&&r.baseRevision>=0?r.baseRevision:null,updatedAt:String(r.updatedAt||''),fields:clean(r.fields)};});
  }catch(e){status='文件内录入数据未能读取，请保留原文件后检查。';}
  function record(key){
    if(memory[key])return memory[key];
    var r=embedded[key]||null;
    try{var local=JSON.parse(localStorage.getItem(storageKey(key))||'null');if(validRecord(local,key)&&(!r||String(local.updatedAt)>r.updatedAt))r={store:identity,period:key,updatedAt:String(local.updatedAt||''),fields:clean(local.fields)};}catch(e){}
    return r;
  }
  var sourceGet=getBossManual,sourceSave=saveBossManual;
  getBossManual=function(){
    if(hasArchive){
      var key=auditPeriodKey(),state=manualState(key),saved=embedded[key];
      if(saved&&!state.htmlRestored){
        state.htmlRestored=true;
        var changes={};Object.keys(saved.fields).forEach(function(k){if(JSON.stringify(saved.fields[k])!==JSON.stringify((state.record.fields||{})[k]))changes[k]=saved.fields[k];});
        if(Object.keys(changes).length){
          if(Object.keys(state.pending).length&&state.baseRevision!==saved.baseRevision)state.conflict=true;
          else if(!Object.keys(state.pending).length)state.baseRevision=saved.baseRevision;
          state.pending=Object.assign(changes,state.pending);manualRemember(key);
        }
      }
      return clone(sourceGet.apply(this,arguments));
    }
    var base=sourceGet.apply(this,arguments);
    var r=record(auditPeriodKey());return clone(Object.assign({},base,r?r.fields:{}));
  };
  function showStatus(){var el=document.getElementById('manualHTMLStatus');if(el)el.textContent=status;}
  saveBossManual=function(value,defer){
    var key=auditPeriodKey();
    if(!validKey(key))return;
    if(hasArchive)sourceSave.call(this,value,defer);
    var r={store:identity,period:key,updatedAt:new Date().toISOString(),fields:clean(value)};
    memory[key]=r;dirty=true;
    if(!hasArchive){try{sourceSave.call(this,value,defer);}catch(e){}}
    try{
      var text=JSON.stringify(r);localStorage.setItem(storageKey(key),text);
      if(localStorage.getItem(storageKey(key))!==text)throw new Error('Storage readback failed');
      status='已在本浏览器暂存；请保存HTML，把录入值写入文件。';
    }catch(e){status='浏览器无法持久保存，数据暂留本页；请立即点击「保存数据到HTML」。';}
    showStatus();
  };
  function capture(el){
    if(!el||!el.getAttribute)return;
    var field=map[el.getAttribute('data-bm')];if(!field)return;
    var raw=el.value,v=(field==='sample_products'||field==='order_products')?raw:raw===''?null:Number(raw);
    if(typeof v==='number'&&(!Number.isFinite(v)||v<0))return;
    var m=getBossManual();m[field]=v;saveBossManual(m,true);
  }
  document.addEventListener('input',function(event){capture(event.target);});
  function captureCurrent(){document.querySelectorAll('#panel-boss [data-bm]').forEach(capture);}
  function snapshot(){
    var entries={};
    Object.keys(D.audit_periods||{}).forEach(function(key){
      var r=record(key);
      if(hasArchive&&MANUAL.states&&MANUAL.states[key]){
        var state=MANUAL.states[key],base=((D.audit_periods[key]||{}).boss||{}).manual||{};
        r={store:identity,period:key,end:manualScope(key).end,baseRevision:state.baseRevision,updatedAt:new Date().toISOString(),fields:clean(Object.assign({},base,r?r.fields:{},(state.record||{}).fields||{},state.pending||{}))};
      }
      if(r)entries[key]=clone(r);
    });
    var current=auditPeriodKey(),values=clean(getBossManual());
    entries[current]={store:identity,period:current,updatedAt:new Date().toISOString(),fields:values};
    if(hasArchive){entries[current].baseRevision=manualState(current).baseRevision;entries[current].end=manualScope(current).end;}
    return {format:'dashboard-manual-html/v1',store:identity,entries:entries};
  }
  function withSnapshot(html,bundle){
    var json=JSON.stringify(bundle).replace(/</g,'\\u003c').replace(/\u2028/g,'\\u2028').replace(/\u2029/g,'\\u2029');
    html=html.replace(/<script\b[^>]*\bid=["']dashboard-manual-snapshot["'][^>]*>[\s\S]*?<\/script\s*>/gi,'');
    if(!/<head(?:\s[^>]*)?>/i.test(html))throw new Error('面板缺少完整文档，未保存');
    return html.replace(/<head(?:\s[^>]*)?>/i,function(head){return head+'<scr'+'ipt id="dashboard-manual-snapshot" type="application/json">'+json+'</scr'+'ipt>';});
  }
  function saveHTML(){
    captureCurrent();
    try{
      var root=document.documentElement.cloneNode(true);
      root.querySelectorAll('.modal-overlay,.pm-overlay,dialog[open]').forEach(function(el){el.remove();});
      var html='<!DOCTYPE html>\n'+withSnapshot(root.outerHTML,snapshot());
      var name=String(D.meta.store_name||'店铺').replace(/[\\/:*?"<>|]/g,'_')+'_经营面板_含已填数据_'+new Date().toISOString().slice(0,10)+'.html';
      _downloadHTML(name,html);dirty=false;status='已生成含录入值的HTML，请保留下载文件；下次打开该文件。';
    }catch(e){status='保存文件失败，数据仍在本页，请重试：'+e.message;}
    showStatus();
  }
  function attach(){
    if(document.getElementById('manualHTMLSave')){showStatus();return;}
    var first=document.querySelector('#panel-boss [data-bm]'),section=first&&first.closest('.boss-sec');
    if(!section)return;
    section.insertAdjacentHTML('afterbegin','<div class="flex mb8" style="gap:8px;flex-wrap:wrap"><button class="btn" type="button" id="manualHTMLSave">保存数据到HTML</button><span id="manualHTMLStatus" class="muted small" role="status" aria-live="polite"></span></div>');
    document.getElementById('manualHTMLSave').onclick=saveHTML;showStatus();
  }
  var sourceBoss=renderBoss;
  renderBoss=function(){var result=sourceBoss.apply(this,arguments);attach();return result;};
  window.manualHTMLSnapshot=snapshot;
  window.manualHTMLWithSnapshot=withSnapshot;
  window.saveManualDashboardHTML=saveHTML;
  document.addEventListener('DOMContentLoaded',attach);
  window.addEventListener('beforeunload',function(event){if(dirty){event.preventDefault();event.returnValue='';}});
})();
