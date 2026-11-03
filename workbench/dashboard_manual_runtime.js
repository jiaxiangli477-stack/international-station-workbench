/* Manual inputs survive browser reloads and dashboard regeneration without crossing periods. */
var MANUAL={states:Object.create(null),requests:Object.create(null),bridge:null,history:D.manual_history||{format:'workbench-dashboard-manual/v1',store:String(D.meta.store_id),entries:[]}};
// The archive bridge stays on the owner origin; HTTP reports run on localhost.
var MANUAL_ORIGIN='http://127.0.0.1:'+(location.port||'8796');
function manualScope(key){var parts=key.split(':'),a=D.audit_periods[key],p=a&&a.period||{};return {store:String(D.meta.store_id),kind:parts[0],start:parts[1],end:p[parts[0]+'_end']||''};}
function manualState(key){
  if(!MANUAL.states[key]){
    var a=(D.audit_periods||{})[key]||{},record=a.manual_record||{revision:0,fields:{}};
    var state={record:record,pending:{},baseRevision:record.revision||0,status:record.revision?'已载入留存记录 · 版本 '+record.revision:'尚无留存记录',loaded:false,loading:false,saving:false,conflict:false};
    try{
      var saved=JSON.parse(localStorage.getItem(auditStorageKey('manual_pending_'+key))||'{}')||{},scope=manualScope(key);
      if(saved.version===1){
        if(['store','kind','start','end'].every(function(k){return saved[k]===scope[k];})&&saved.changes&&typeof saved.changes==='object'&&!Array.isArray(saved.changes)){
          state.pending=saved.changes;state.baseRevision=Number.isInteger(saved.baseRevision)&&saved.baseRevision>=0?saved.baseRevision:null;
        }
      }else if(typeof saved==='object'&&!Array.isArray(saved)&&Object.keys(saved).length){state.pending=saved;state.baseRevision=null;}
    }catch(e){}
    MANUAL.states[key]=state;
  }
  return MANUAL.states[key];
}
function getBossManual(){
  var key=auditPeriodKey(),m=Object.assign({},(D.boss||{}).manual||{}),state=MANUAL&&manualState(key);
  if(state&&state.record.revision)Object.assign(m,state.record.fields);
  else try{var old=JSON.parse(localStorage.getItem(bossKey())||'null');if(old)Object.keys(m).forEach(function(k){if(k in old)m[k]=old[k];});}catch(e){}
  if(state)Object.assign(m,state.pending);return JSON.parse(JSON.stringify(m));
}
function manualStatus(key){var el=document.getElementById('manualSaveStatus');if(el&&key===auditPeriodKey())el.textContent=manualState(key).status;}
function manualRemember(key){var state=manualState(key);try{localStorage.setItem(auditStorageKey('manual_pending_'+key),JSON.stringify(Object.assign({version:1,baseRevision:state.baseRevision,changes:state.pending},manualScope(key))));}catch(e){state.status='浏览器暂存不可用，请立即导出录入备份';}manualStatus(key);}
function saveBossManual(value,defer){
  var key=auditPeriodKey(),state=manualState(key),before=getBossManual();
  Object.keys(value).forEach(function(k){if(JSON.stringify(value[k])!==JSON.stringify(before[k]))state.pending[k]=value[k];});
  if(!Object.keys(state.pending).length){manualStatus(key);return;}
  try{localStorage.setItem(bossKey(),JSON.stringify(value));}catch(e){}
  state.status='本机已暂存，正在保存到工作台…';manualRemember(key);clearTimeout(state.timer);
  if(defer)state.timer=setTimeout(function(){manualFlush(key);},450);else manualFlush(key);
}
function captureManualInput(el){
  var map={acq:'acquisition',qc:'quality_customers',cac:'cac',newcount:'new_count',sample:'sample_orders',sampleprod:'sample_products',annual:'annual_fee',orderprod:'order_products',wendin:'wendin',topshow:'topshow',brand:'brand_ad',adov:'ad_spend_override'};
  var key=map[el.getAttribute('data-bm')];if(!key)return;
  var value=key==='sample_products'||key==='order_products'?el.value:el.value===''?null:Number(el.value);
  if(typeof value==='number'&&(!Number.isFinite(value)||value<0))return;
  var m=getBossManual();m[key]=value;saveBossManual(m,true);
}
document.addEventListener('input',function(event){if(event.target.matches&&event.target.matches('#panel-boss [data-bm]'))captureManualInput(event.target);});
function manualTarget(){if(window.parent!==window)return window.parent;if(MANUAL.bridge&&!MANUAL.bridge.closed)return MANUAL.bridge;return null;}
function manualRequest(payload){return new Promise(function(resolve,reject){
  var target=manualTarget();if(!target){reject(new Error('独立面板尚未连接工作台；当前录入仍在本机，请连接或导出备份。'));return;}
  var id=Date.now().toString(36)+'_'+Math.random().toString(36).slice(2);
  var timer=setTimeout(function(){delete MANUAL.requests[id];reject(new Error('留存服务未响应；本机录入保留，请重连或导出备份。'));},8000);
  MANUAL.requests[id]={resolve:resolve,reject:reject,timer:timer};
  target.postMessage({type:'workbench-dashboard-manual',requestId:id,payload:payload},MANUAL_ORIGIN);
});}
window.addEventListener('message',function(event){
  if(event.origin!==MANUAL_ORIGIN||event.source!==manualTarget())return;
  var message=event.data||{};
  if(message.type==='workbench-dashboard-manual-ready'){manualLoad(auditPeriodKey(),true);return;}
  if(message.type!=='workbench-dashboard-manual-result')return;
  var r=MANUAL.requests[message.requestId];if(!r)return;clearTimeout(r.timer);delete MANUAL.requests[message.requestId];
  if(message.ok)r.resolve(message.data);else{var error=new Error((message.data||{}).error||'录入保存失败');error.status=message.status;error.current=(message.data||{}).current;r.reject(error);}
});
function manualSnapshotId(){var match=/^\/shared\/([a-f0-9]{24})\//.exec(location.pathname);return match?match[1]:'';}
function connectManualArchive(){
  if(window.parent!==window){manualLoad(auditPeriodKey(),true);return;}
  if(MANUAL.bridge&&!MANUAL.bridge.closed){manualLoad(auditPeriodKey(),true);return;}
  var query=new URLSearchParams({snapshot:manualSnapshotId(),returnOrigin:location.protocol==='file:'?'null':location.origin});
  MANUAL.bridge=window.open(MANUAL_ORIGIN+'/dashboard-manual.html?'+query,'_blank','width=700,height=420');
  var state=manualState(auditPeriodKey());state.status=MANUAL.bridge?'正在连接工作台留存窗口…':'连接窗口未打开；请允许此页面弹出连接窗口，或使用录入备份。';manualStatus(auditPeriodKey());
}
async function manualLoad(key,force){
  var state=manualState(key);if(state.loading||state.loaded&&!force)return;state.loading=true;
  try{
    var result=await manualRequest(Object.assign({action:'load'},manualScope(key)));
    var local=getBossManual();
    if(Object.keys(state.pending).length&&(state.baseRevision===null||state.baseRevision!==result.record.revision)){state.conflict=true;state.status='档案版本冲突或本机基准未知，待保存值保留；请备份后核对，不会自动覆盖。';}
    state.record=result.record;state.loaded=true;
    if(!Object.keys(state.pending).length)state.baseRevision=state.record.revision||0;
    if(result.backup)MANUAL.history=result.backup;
    // Only known store+period local entries can be migrated; unscoped old entries are never guessed.
    if(!state.record.revision&&key===auditPeriodKey()){
      try{if(localStorage.getItem(bossKey())&&!Object.keys(state.pending).length){Object.keys(local).forEach(function(k){if(local[k]!=null&&local[k]!==''&&JSON.stringify(local[k])!=='[]')state.pending[k]=local[k];});if(Object.keys(state.pending).length){state.baseRevision=null;state.conflict=true;state.status='旧本机录入基准未知，请备份后核对，不会自动覆盖。';manualRemember(key);}}}catch(e){}
    }
    if(!state.conflict)state.status=state.record.revision?'已从工作台恢复 · 版本 '+state.record.revision:'已连接；填写后自动留存';
    if(key===auditPeriodKey())renderBoss();
    if(Object.keys(state.pending).length&&!state.conflict)manualFlush(key);
  }catch(e){state.status=e.message;manualStatus(key);}finally{state.loading=false;}
}
async function manualFlush(key){
  var state=manualState(key);if(state.saving||state.conflict||!Object.keys(state.pending).length)return;
  if(!state.loaded){await manualLoad(key,false);if(!state.loaded)return;}
  if(state.saving||state.conflict||state.baseRevision===null)return;state.saving=true;
  var sent=Object.assign({},state.pending);
  try{
    var result=await manualRequest(Object.assign({action:'save',revision:state.baseRevision,changes:sent},manualScope(key)));
    state.record=result.record;
    state.baseRevision=state.record.revision;
    Object.keys(sent).forEach(function(k){if(JSON.stringify(state.pending[k])===JSON.stringify(sent[k]))delete state.pending[k];});
    var scope=manualScope(key);state.status='已自动保存到工作台 · 版本 '+state.record.revision+' · '+scope.start+' ~ '+scope.end;
    if(state.record.id&&!MANUAL.history.entries.some(function(r){return r.id===state.record.id;}))MANUAL.history.entries.push(state.record);
    manualRemember(key);
  }catch(e){state.status=e.message;if(e.status===409){state.conflict=true;state.status+=' 本机待保存值已保留，可先导出备份。';}manualStatus(key);}
  finally{state.saving=false;}
  if(!state.conflict&&Object.keys(state.pending).length&&state.status.indexOf('已自动保存')===0)manualFlush(key);
}
function manualLocalBackup(){
  var entries=(MANUAL.history.entries||[]).slice();
  Object.keys(MANUAL.states).forEach(function(key){var s=MANUAL.states[key];if(!Object.keys(s.pending).length)return;var fields=Object.assign({},s.record.fields,s.pending),id=Array.from({length:32},function(){return Math.floor(Math.random()*16).toString(16);}).join('');entries.push(Object.assign({},manualScope(key),{id:id,revision:(s.record.revision||0)+1,updatedAt:new Date().toISOString(),source:'local-pending',fields:fields}));});
  return {format:'workbench-dashboard-manual/v1',store:String(D.meta.store_id),entries:entries};
}
async function exportManualArchive(){
  var bundle;
  try{var result=await manualRequest(Object.assign({action:'export'},manualScope(auditPeriodKey())));MANUAL.history=result.backup;bundle=manualLocalBackup();}
  catch(e){bundle=manualLocalBackup();}
  downloadRankingFile(String(D.meta.store_id)+'_录入留存备份.json',JSON.stringify(bundle,null,2),'application/json;charset=utf-8;');
}
async function importManualArchive(file){
  if(!file)return;var state=manualState(auditPeriodKey());
  try{if(file.size>1048576)throw new Error('备份文件过大');var backup=JSON.parse(await file.text());
    if(backup.format!=='workbench-dashboard-manual/v1'||backup.store!==String(D.meta.store_id))throw new Error('备份店铺不匹配，不会导入其他店铺数据。');
    var result=await manualRequest(Object.assign({action:'import',backup:backup},manualScope(auditPeriodKey())));
    MANUAL.history=result.backup;state.loaded=false;state.conflict=false;await manualLoad(auditPeriodKey(),true);state.status='已导入 '+result.imported+' 条留存记录；已有冲突不会被覆盖。';manualStatus(auditPeriodKey());
  }catch(e){state.status=e.message+' 原录入记录保留。';manualStatus(auditPeriodKey());}
}
function viewManualHistory(){
  var old=document.getElementById('manualHistoryDialog');if(old)old.remove();
  var dialog=document.createElement('dialog');dialog.id='manualHistoryDialog';dialog.style.cssText='width:min(900px,92vw);max-height:85vh;border:1px solid #ccd3dd;border-radius:10px;padding:20px;';
  var entries=manualLocalBackup().entries,labels={acquisition:'获客数量',quality_customers:'优质获客数量',cac:'获客成本',new_count:'新品数量',sample_orders:'样品单数量',sample_products:'样品产品',annual_fee:'年费',order_products:'订单产品',wendin:'问鼎',topshow:'顶展',brand_ad:'品牌广告',ad_spend_override:'广告花费覆盖',new_selection:'已选新品ID'};
  var rows=entries.slice().reverse().map(function(r){var fields=r.fields||{},detail=Object.keys(fields).map(function(k){var value=fields[k];return '<div><b>'+esc(labels[k]||'录入值')+'：</b>'+esc(value==null?'未填写':Array.isArray(value)?value.join('、'):value)+'</div>';}).join('');return '<tr><td>'+esc((r.kind==='week'?'周 ':'月 ')+r.start+' ~ '+r.end)+'</td><td>'+esc(r.revision)+'</td><td>'+esc(fields.new_count==null?'未填写':fields.new_count)+'</td><td>'+esc(fields.sample_orders==null?'未填写':fields.sample_orders)+'</td><td><details><summary>查看录入明细</summary>'+detail+'</details></td></tr>';}).join('');
  dialog.innerHTML='<h3>本店录入历史 · '+entries.length+' 个版本</h3><p>按店铺与统计期间保留；历史值不会自动成为新一周的数据。</p><button class="btn" id="manualHistoryClose">关闭</button><div style="overflow:auto;max-height:60vh"><table style="width:100%"><thead><tr><th>统计期间</th><th>版本</th><th>新品数</th><th>样品单</th><th>录入明细</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
  document.body.appendChild(dialog);dialog.querySelector('button').onclick=function(){dialog.close();dialog.remove();};dialog.showModal();
}
var manualOriginalRenderBoss=renderBoss;
renderBoss=function(){
  var result=manualOriginalRenderBoss(),input=document.querySelector('#panel-boss [data-bm]'),section=input&&input.closest('.boss-sec');
  if(section){
    var heading=section.querySelector('h3');if(heading)heading.textContent='运营录入区（按店铺和期间留存）';
    section.insertAdjacentHTML('afterbegin','<div class="flex mb8" style="gap:8px;flex-wrap:wrap"><span id="manualSaveStatus" role="status"></span><button class="btn" type="button" onclick="connectManualArchive()">连接 / 同步留存</button><button class="btn" type="button" onclick="exportManualArchive()">备份录入数据</button><button class="btn" type="button" onclick="document.getElementById(\'manualImportFile\').click()">导入备份</button><button class="btn" type="button" onclick="viewManualHistory()">查看历史录入</button><input type="file" id="manualImportFile" accept="application/json,.json" style="display:none" onchange="importManualArchive(this.files[0]);this.value=\'\'"></div>');
    section.querySelectorAll('div').forEach(function(el){if(el.children.length===0&&el.textContent.includes('把这些值告诉我'))el.textContent='工作台内填写会自动留存；独立面板请连接留存窗口。离线时保留本机暂存，并可备份JSON。重做同一期间会恢复历史值，新周/新月分别记录。';});
    manualStatus(auditPeriodKey());manualLoad(auditPeriodKey(),false);
  }
  return result;
};
