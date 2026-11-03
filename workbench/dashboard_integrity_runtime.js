/* Period selection, full-result exports and source disclosure for the existing UI. */
var AUDIT_BASE = {meta:D.meta, bearing:D.bearing,sections:D.v4_sections, new_candidates:D.new_candidates,
  scores:D.v4_scores, ad_plans:D.ad_plans, health:D.health, boss:D.boss};
var RANKINGS = Object.create(null);
function auditPeriodKey(){
  var items=PERIOD==='month' ? D.months||[] : D.weeks||[];
  var index=PERIOD==='month' ? SELECTED_MONTH : SELECTED_WEEK;
  var p=items[index<0?items.length-1:index]||{};
  return PERIOD+':'+(p[PERIOD+'_start']||'');
}
function auditPeriod(){ return (D.audit_periods||{})[auditPeriodKey()]||{}; }
function syncAuditPeriod(){
  var a=auditPeriod(); if(!a.period) return;
  D.boss=a.boss; D.lists=a.lists; D.lists_month=a.lists; D.health=a.health;
  D.ad_products=a.ad_products; D.new_candidates=a.products;
  // These are generated defaults. note()/noteBox() still prefer the user's saved note.
  var hh=a.health||{},levels=hh.levels||[];
  var healthNote=hh.valid_cnt==null?'该期间未采集可核验产品明细，产品分层与零询盘数量未知。':
    '本期产品明细 '+num(hh.valid_cnt)+' 条；'+levels.map(function(l){return l.label+' '+num(l.count);}).join(' / ')+'。有询盘产品 '+num(hh.inquiry_products)+'，零询盘产品 '+num(hh.zero_inquiry)+'。';
  healthNote+=' 店铺有效商品 '+num(a.period.valid_prod_cnt)+'（店铺汇总独立字段，与本期产品明细数分别统计）。';
  D.section_notes=Object.assign({},D.section_notes,{health:healthNote,staff:(D.staff_cs||[]).length?'子账号数据为采集快照，须核对各指标期间，不能据此认定当前历史期间的接待人数。':'该期间子账号报表未匹配；空表不表示0人接待，须核对原始日期与统计窗口后展示。',zero:'无广告点击不等于零花费；该榜仅作为待核对机会池。',eff:'同品广告点击与商机并存；单品花费和广告归因未提供，不能据此判定低耗。',opp:'本期完整产品明细按询盘+TM未去重加总排序；不是独立买家数。'});
  D.summary={executive_summary:bossPeriodLabel()+'：搜索曝光 '+num(a.period.se_imps)+'，搜索点击 '+num(a.period.se_clk)+'，询盘 '+num(a.period.fb_cnt)+'，TM '+num(a.period.fb_tm_uv)+'，成交订单 '+num(a.period.suc_ord_cnt)+'，成交金额 '+money(a.period.suc_ord_amt)+'。',
    primary_problem:a.products.length?'店铺汇总与产品明细需分别使用，不能把产品订单或TM逐品加总当成店铺成交订单或去重人数。':'该期间未采集产品明细，榜单不可用。',
    primary_root_cause:'接口统计对象、订单状态、归因和去重范围不同；缺失账户数据、手填字段单独保留，不能补0。',top_opportunities:[]};
  var s=a.boss.spend;
  D.ad_plans={account:{spend:s.ad_spend,clicks:s.ad_clicks,impressions:s.ad_imps,cpc:s.ad_cpc,cpl:s.ad_cpl,opp_cnt:s.ad_opp},
    campaigns:[],search_note:'当前期间账户汇总；单品花费、归因、计划报告缺失时不推断为零或低耗'};
  // Scoring and execution advice are pinned to the generation snapshot, never re-labelled as historical.
  D.v4_scores=AUDIT_BASE.scores;
  RANKINGS=Object.create(null);
}
function getLists(){return auditPeriod().lists||{};}
function selectedWeek(){
  var a=D.weeks||[]; return a[SELECTED_WEEK<0?a.length-1:SELECTED_WEEK]||null;
}
function getFunnel(){
  var p=auditPeriod().period||{};
  var f=PERIOD==='month'?monthToFunnel(p):weekToFunnel(p);
  f=f.filter(function(x){return x.key!=='total_clk' && x.key!=='pv_cnt';});
  f.splice(4,0,{key:'total_clk',label:'全店点击',cur:p.total_clk,note:'平台 totalClkCnt；不可用浏览量或渠道相加替代。'},
    {key:'pv_cnt',label:'浏览量 PV',cur:p.pv_cnt,note:'pvCnt；浏览量与点击次数分别统计。'});
  f.forEach(function(x){
    if(x.fmt==='money'||x.fmt==='pct')x.unit='';
    if(x.key==='suc_ord_cnt')x.label='成交订单（sucOrdCnt）';
    if(x.key==='uv_payord_rate')x.note='平台 uvPayordRate 原始字段；不以成交买家数÷访客数覆盖。两者对象、归因或窗口可能不同，差异待平台核实。';
    if(x.key==='opp'){ x.cur=p.opp;x.rival_avg=null;x.rival_good=null;x.note='询盘次数 + TM咨询人数的未去重加总；平台 abCnt='+num(p.platform_ab_cnt)+'，是独立字段，不等同于此加总。'; }
  });
  return f;
}
function getBearing(){var rolling=(AUDIT_BASE.bearing||[]).filter(function(b){return b.key!=='uv_payord';}).map(function(b){return Object.assign({},b,{label:b.label+'（近30天）'});});var p=auditPeriod().period||{};rolling.push({key:'uv_payord',label:'访客成交率（所选期间，平台原始字段）',cur:p.uv_payord_rate,fmt:'pct',unit:'%',rival_avg:p.uv_payord_ra,rival_good:p.uv_payord_rg});return rolling;}
function auditStarTrack(sr){var tracks=sr.tracks||[];return tracks.find(function(t){return t.track_type===sr.predict_track_type;})||tracks[0]||{};}
function auditStarPredictionHTML(sr){
  var track=auditStarTrack(sr),predicted=auditNumber(sr.display_star),current=auditNumber(sr.level_star);
  if(predicted==null)predicted=auditNumber(track.star);
  if(predicted==null||!Number.isFinite(predicted))return '<span class="tag">平台预测等级未提供</span>';
  var lower=current!=null&&predicted<current;
  return '<span class="tag '+(lower||(track.alert||{}).down===true?'danger':'neutral')+'">平台预测'+esc(predicted)+'星'+(track.track_name?' · '+esc(track.track_name):'')+(lower?'（低于本月等级）':'')+'</span>';
}
function money(v){return v==null||v===''?'—':'$'+Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
function gapHtml(cur,avg,good,lowerBetter){
  if(cur==null)return '<span class="muted">本期缺数据，未比较</span>';
  var parts=[];[[good,'同行优秀'],[avg,'同行平均']].forEach(function(pair){var ref=pair[0];if(ref==null)return;var delta=cur-ref,ok=lowerBetter?delta<=0:delta>=0;parts.push(pair[1]+' '+fmtg(ref)+' <span class="'+(ok?'ok':'bad')+'">('+(delta>0?'高于':delta<0?'低于':'持平')+(delta?' '+fmtg(Math.abs(delta)):'')+')</span>');});
  return parts.length?parts.join(' · '):'<span class="muted">同行 —</span>';
}
function bossPeriodLabel(){var p=auditPeriod().period||{};return (p[PERIOD+'_start']||'')+' ~ '+(p[PERIOD+'_end']||'');}
function bossKey(){return 'gos_boss_manual_v2_'+(D.meta.store_id||window.V4_STORE||'store')+'_'+auditPeriodKey();}
function getBossManual(){
  var m=Object.assign({},(D.boss||{}).manual||{});
  try{var v=JSON.parse(localStorage.getItem(bossKey())||'null');if(v&&typeof v==='object')Object.keys(m).forEach(function(k){if(k in v)m[k]=v[k];});}catch(e){}
  return m;
}
function auditStorageKey(name){return 'workbench_'+D.meta.store_id+'_'+name;}
function getTrack(){try{return JSON.parse(localStorage.getItem(auditStorageKey('new_track'))||'{}');}catch(e){return {};}}
function setTrack(value){try{localStorage.setItem(auditStorageKey('new_track'),JSON.stringify(value));}catch(e){}}
function getNewDates(){try{return JSON.parse(localStorage.getItem(auditStorageKey('new_dates'))||'{}');}catch(e){return {};}}
function setNewDate(pid,date){var dates=getNewDates();if(date)dates[pid]=date;else delete dates[pid];try{localStorage.setItem(auditStorageKey('new_dates'),JSON.stringify(dates));}catch(e){}}
function auditNumber(v){return v==null||v===''?null:Number(v);}
function auditSum(a,b){return a==null||b==null?null:a+b;}
function auditOtherSpend(m){var vals=['annual_fee','wendin','topshow','brand_ad'].map(function(k){return auditNumber(m[k]);});return vals.some(function(v){return v==null;})?null:vals.reduce(function(a,b){return a+b;},0);}
function _n(v){return v==null||v===''?'未提供 / 未填写':Number(v).toLocaleString();}
function _m(v){return v==null||v===''?'未提供 / 未填写':'¥'+Number(v).toLocaleString(undefined,{maximumFractionDigits:2});}
function weeklyOnlyNote(){return '<div class="insight warn">以下辅助分析固定为采集快照 '+esc(AUDIT_BASE.meta.week_label)+'；不随历史周/月重算。回复三项为截至采集时的近30天滚动口径。</div>';}
function rankingRows(rows){
  var seen=Object.create(null);return (rows||[]).map(function(p){
    if(p.product_id!=null)return p;
    var url=p.url||p.product_url||p.detail_url||'',match=/^https:\/\/(?:www\.)?alibaba\.com\/product-detail\/[^?#]*_(\d+)\.html(?:[?#]|$)/.exec(url);
    return match?Object.assign({},p,{product_id:match[1]}):p;
  }).filter(function(p){
    var id=p.product_id==null?'':String(p.product_id).trim();if(!/^\d+$/.test(id)||seen[id])return false;seen[id]=true;return true;
  });
}
function rankingIds(rows){return rankingRows(rows).map(function(p){return String(p.product_id).trim();});}
function rankingToolbar(key,rows,label){
  var pinned=['competitors','market_products','summary_market','exec_actions'].includes(key);
  RANKINGS[key]={rows:rankingRows(rows),label:label||key,period:pinned?'采集快照 '+AUDIT_BASE.meta.week_label:bossPeriodLabel()};
  var omitted=(rows||[]).length-RANKINGS[key].rows.length;
  return '<div class="flex mb8 audit-export" style="gap:8px;flex-wrap:wrap"><button class="btn" type="button" onclick="openRankingExport(\''+key+'\')">导出ID / 查看全部</button><button class="btn" type="button" onclick="exportRankingCSV(\''+key+'\')">导出明细CSV</button><span class="muted small">'+RANKINGS[key].rows.length+' 个去重产品 · 当前筛选全量结果'+(pinned?' · '+esc(RANKINGS[key].period):'')+(omitted>0?'（重复或缺少真实ID '+omitted+' 行已排除）':'')+'</span></div>';
}
function rankingFilter(key){
  var r=RANKINGS[key]||{rows:[]};
  if(key==='ai')return filteredAIRows();
  if(key.indexOf('list_')===0){var fc=(document.getElementById('filter_'+key.slice(5))||{}).value||'';return r.rows.filter(function(p){return !fc||p.category===fc;});}
  if(key==='new_tracking')return filteredNewTracking();
  if(key==='boss_pool'){var q=((document.getElementById('bossNewSearch')||{}).value||'').toLowerCase();return r.rows.filter(function(p){return !q||((p.title||'')+' '+p.product_id).toLowerCase().includes(q);});}
  if(key==='new_manager'){var q=((document.getElementById('np_search')||{}).value||'').toLowerCase();return r.rows.filter(function(p){return !q||((p.title||'')+' '+p.product_id).toLowerCase().includes(q);});}
  if(key==='competitors'){var fc=(document.getElementById('compCat')||{}).value||'';return r.rows.filter(function(p){return !fc||p.category===fc;});}
  if(key==='boss_selected')return newSelectionRows();
  return r.rows;
}
function downloadRankingFile(name,text,type){
  var url=URL.createObjectURL(new Blob([text],{type:type||'text/plain;charset=utf-8;'}));
  var a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(url);},1500);
}
function rankingFilename(key){return (D.meta.store_id||'store')+'_'+auditPeriodKey().replace(':','_')+'_'+key;}
function csvSafe(v){var s=v==null?'':String(v);if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}
function exportRankingCSV(key,rows){
  rows=rows||rankingFilter(key);var daily=(auditPeriod().provenance||{}).mode==='daily_rollup';var fields=['product_id','title','category','total_imps','total_clk','inquiries','tm','opp','orders','gmv','observation_days','tm_daily_sum'];
  var lines=[['期间','排名'].concat(fields.map(function(k){return k==='orders'?'created_orders_crtOrd'+(daily?'_daily_sum':''):k==='gmv'?'rtsOnlineAmt_USD'+(daily?'_daily_sum':''):daily&&k==='inquiries'?'inquiries_daily_sum':daily&&k==='tm'?'TM_weekly_unique_unavailable':k==='tm_daily_sum'?'TM_daily_sum_not_weekly_unique':k==='observation_days'?'observed_days_out_of_7':k;})).map(csvSafe).join(',')];
  rankingRows(rows).forEach(function(p,i){lines.push([(RANKINGS[key]||{}).period||bossPeriodLabel(),i+1].concat(fields.map(function(k){return p[k];})).map(csvSafe).join(','));});
  downloadRankingFile(rankingFilename(key)+'.csv','\uFEFF'+lines.join('\r\n'),'text/csv;charset=utf-8;');
}
var EXPORT_MODAL_ROWS=[];
function exportModalRows(){var q=((document.getElementById('rankSearch')||{}).value||'').toLowerCase();return EXPORT_MODAL_ROWS.filter(function(p){return !q||((p.title||'')+' '+p.product_id+' '+(p.category||'')).toLowerCase().includes(q);});}
function updateRankingModal(){
  var rows=exportModalRows(),ids=rankingIds(rows);document.getElementById('rankIds').value=ids.join('\n');
  document.getElementById('rankCount').textContent=ids.length+' 个去重ID；包含全部匹配结果，不受原表50/100条显示上限影响。';
  var page=Number((document.getElementById('rankPage')||{}).value||0),max=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,max-1);
  document.getElementById('rankPage').innerHTML=Array.from({length:max},function(_,i){return '<option value="'+i+'"'+(i===page?' selected':'')+'>第 '+(i+1)+' / '+max+' 页</option>';}).join('');
  document.getElementById('rankPreview').innerHTML=rows.slice(page*50,page*50+50).map(function(p,i){return '<tr><td>'+(page*50+i+1)+'</td><td>'+esc(p.product_id)+'</td><td>'+esc(p.title||'')+'</td></tr>';}).join('');
}
function openRankingExport(key){
  var old=document.getElementById('rankExportModal');if(old)old.remove();EXPORT_MODAL_ROWS=rankingRows(rankingFilter(key));
  var box=document.createElement('div');box.id='rankExportModal';box.className='pm-overlay';box.setAttribute('role','dialog');box.setAttribute('aria-label','导出产品ID');box.style.cssText='position:fixed;inset:0;background:#0009;z-index:10000;overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:28px';
  box.innerHTML='<div class="card" style="width:min(1000px,95vw);max-height:90vh;overflow:auto;background:var(--bg,#fff)"><h3>'+esc((RANKINGS[key]||{}).label||key)+' · '+esc((RANKINGS[key]||{}).period||bossPeriodLabel())+'</h3><p id="rankCount"></p><div class="flex mb8" style="gap:8px;flex-wrap:wrap"><input id="rankSearch" aria-label="筛选导出产品" placeholder="按产品ID、名称或类目筛选" oninput="updateRankingModal()"><button class="btn" id="rankCopy">复制ID</button><button class="btn" id="rankDownload">下载ID文本</button><button class="btn" id="rankCSV">下载筛选明细CSV</button><button class="btn" id="rankClose">关闭</button></div><textarea id="rankIds" aria-label="完整产品ID" readonly style="width:100%;height:150px;font-family:monospace"></textarea><p class="muted small">每行一个原始ID。CSV导入Excel时请将产品ID列指定为文本，避免自动数值转换。</p><select id="rankPage" aria-label="结果页码" onchange="updateRankingModal()"></select><table style="width:100%"><thead><tr><th>排名</th><th>产品ID</th><th>名称</th></tr></thead><tbody id="rankPreview"></tbody></table><div id="rankCopyStatus" role="status"></div></div>';
  document.body.appendChild(box);var prior=document.activeElement;
  function close(){box.remove();if(prior&&prior.focus)prior.focus();}
  document.getElementById('rankClose').onclick=close;box.addEventListener('keydown',function(e){if(e.key==='Escape')close();if(e.key==='Tab'){var nodes=box.querySelectorAll('button,input,textarea,select');var first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
  document.getElementById('rankDownload').onclick=function(){downloadRankingFile(rankingFilename(key)+'_IDs.txt',rankingIds(exportModalRows()).join('\r\n'));};
  document.getElementById('rankCSV').onclick=function(){exportRankingCSV(key,exportModalRows());};
  document.getElementById('rankCopy').onclick=async function(){var text=rankingIds(exportModalRows()).join('\n');try{await navigator.clipboard.writeText(text);document.getElementById('rankCopyStatus').textContent='已复制 '+rankingIds(exportModalRows()).length+' 个ID';}catch(e){document.getElementById('rankIds').select();document.getElementById('rankCopyStatus').textContent='请按 Ctrl+C 复制已选中的完整ID';}};
  updateRankingModal();document.getElementById('rankSearch').focus();
}
function auditBanner(){
  var a=auditPeriod();
  return '<p class="muted small audit-disclosure">'+esc(bossPeriodLabel())+' · 产品明细 '+num((a.products||[]).length)+' 条 · 金额 USD / 广告 CNY · 未提供的数据留空</p>';
}
var auditOriginalRenderPeriod=renderPeriod;
renderPeriod=function(){var result=auditOriginalRenderPeriod();var el=document.getElementById('panel-period');if(el)el.insertAdjacentHTML('afterbegin',auditBanner());return result;};
var auditOriginalRenderBoss=renderBoss;
renderBoss=function(){var result=auditOriginalRenderBoss();var el=document.getElementById('panel-boss');if(el){el.insertAdjacentHTML('afterbegin',auditBanner());
  // Old templates supplied zeroes even after the data default was corrected.
  el.querySelectorAll('[data-bm]').forEach(function(inp){var key={acq:'acquisition',qc:'quality_customers',sample:'sample_orders',annual:'annual_fee',wendin:'wendin',topshow:'topshow',brand:'brand_ad',newcount:'new_count'}[inp.getAttribute('data-bm')];if(key&&getBossManual()[key]==null)inp.value='';});
}return result;};
var auditOriginalLevelSection=productLevelSection;
productLevelSection=function(emoji,title,count,rows,sec,key){return auditOriginalLevelSection(emoji,title,count,rows,sec,key).replace('<button id="bossLvlToggle_',rankingToolbar('level_'+key,rows,title)+'<button id="bossLvlToggle_');};
var auditOriginalRenderList=renderList;
renderList=function(title,sub,key,noteKey){var html=auditOriginalRenderList(title,sub,key,noteKey);return html.replace('<div class="card">','<div class="card">'+rankingToolbar('list_'+noteKey,getLists()[key]||[],title));};
var auditOriginalListBody=renderListBody;
renderListBody=function(noteKey){auditOriginalListBody(noteKey);var body=document.getElementById('body_'+noteKey),card=body&&body.closest('.card'),status=card&&card.querySelector('.audit-export .muted');if(status)status.textContent=rankingIds(rankingFilter('list_'+noteKey)).length+' 个去重产品 · 当前筛选全量结果（表内预览最多50项）';};
function filteredAIRows(){
  var fl=(document.getElementById('aiFilterLabel')||{}).value||'',fc=(document.getElementById('aiFilterCat')||{}).value||'',kw=((document.getElementById('aiSearch')||{}).value||'').toLowerCase();
  return ((auditPeriod().products)||[]).filter(function(p){return (!fl||p.label===fl)&&(!fc||p.category===fc)&&(!kw||((p.title||'')+' '+p.product_id).toLowerCase().includes(kw));});
}
var auditOriginalRenderAI=renderAI;
renderAI=function(){auditOriginalRenderAI();window._aiAll=auditPeriod().products||[];var body=document.getElementById('aiTableBody');if(body){var wrap=body.closest('.card');if(wrap){wrap.insertAdjacentHTML('afterbegin',rankingToolbar('ai',window._aiAll,'全部产品诊断'));var sel=document.getElementById('aiFilterCat');if(sel){var cats=Array.from(new Set(window._aiAll.map(function(p){return p.category;}).filter(Boolean)));sel.innerHTML='<option value="">类目：全部</option>'+cats.map(function(c){return '<option>'+esc(c)+'</option>';}).join('');}}}renderAITable();};
function filteredNewTracking(){
  var ds=(document.getElementById('np_from')||{}).value||'',de=(document.getElementById('np_to')||{}).value||'';
  return (D.new_candidates||[]).filter(function(p){var date=newProdDate(p);return isTracked(p.product_id)&&!!date&&(!ds||date>=ds)&&(!de||date<=de);});
}
var auditOriginalRenderNew=renderNewProduct;
renderNewProduct=function(){var html=auditOriginalRenderNew();var toolbar=rankingToolbar('new_tracking',filteredNewTracking(),'追踪新品');var el=document.getElementById('newprod_section');if(el){var old=el.querySelector('.audit-export');if(old)old.remove();el.insertAdjacentHTML('afterbegin',toolbar);}return html.replace('<div id="newprod_section">','<div id="newprod_section">'+toolbar);};
var auditOriginalRenderZero=renderZeroEffect;
renderZeroEffect=function(){
  var rows=auditPeriod().products||[],zero=rows.filter(function(p){return p.total_clk===0&&p.opp===0;});
  var h='<div class="section-title">0效果产品 · 当前期间</div><div class="card"><p>有曝光无点击与零曝光分开处理；缺失指标不归入零效果。</p>';
  [['曝光浪费',zero.filter(function(p){return p.total_imps>0;})],['彻底沉睡',zero.filter(function(p){return p.total_imps===0;})]].forEach(function(pair,i){h+='<h4>'+pair[0]+' '+pair[1].length+' 个</h4>'+rankingToolbar('zero_'+i,pair[1],pair[0]);});return h+'</div>';
};
// Same underlying products belong to different views. Focus keeps entry points, avoids three repeated tables.
var auditOriginalRenderFocus=renderFocus;
renderFocus=function(){auditOriginalRenderFocus();var el=document.getElementById('panel-focus');if(!el)return;el.insertAdjacentHTML('afterbegin',auditBanner());var tables=el.querySelectorAll('table');var defs=[['opp','有商机，抓成交'],['zero_cost','无广告点击机会'],['danger','高点击0商机']];tables.forEach(function(t,i){if(i>=defs.length)return;var def=defs[i],rows=def[0]==='danger'?(auditPeriod().products||[]).filter(function(p){return p.opp===0&&p.total_clk>=4;}):(getLists()[def[0]]||[]);t.parentElement.innerHTML=rankingToolbar('focus_'+def[0],rows,def[1])+'<p class="muted small">与周期榜单共用同一份结果；点击“查看全部”筛选、翻页及导出，避免重复展示。</p>';});
  // State entries keep separate business purposes and all-member export, while previewing three products.
  var stateGrid=el.querySelector('.card .flex'),stateCards=stateGrid?Array.from(stateGrid.children):[];
  (getLists().state_grid||[]).forEach(function(g,i){if(stateCards[i])stateCards[i].insertAdjacentHTML('beforeend',rankingToolbar('state_'+g.state,g.items,g.name));});
};
// Explicit auxiliary snapshot exports, including competitor products. No fabricated product IDs.
function attachAuxiliaryExports(){
  var definitions=[['panel-exec','exec_actions',(D.actions||[]).concat(D.optimizations||[]), '单品优化执行计划（采集快照）'],['panel-compete','competitors',window._comps||[],'竞品对比（外部产品快照）'],['panel-trend','trend_products',auditPeriod().products||[],'单品趋势选择池']];
  definitions.forEach(function(x){var el=document.getElementById(x[0]);if(el&&!el.querySelector('.audit-export')&&x[2].length)el.insertAdjacentHTML('afterbegin',rankingToolbar(x[1],x[2],x[3]));});
}
var auditOriginalNewSelected=renderNewSelected;
function newSelectionRows(){var pool=(D.boss||{}).product_pool||[],ids=getBossManual().new_selection||[];return pool.filter(function(p){return ids.includes(p.product_id);});}
function exportNewSelection(){var rows=newSelectionRows();var html='<!doctype html><html lang="zh"><meta charset="utf-8"><title>新品清单</title><h1>'+esc(D.meta.store_name)+' · '+esc(bossPeriodLabel())+'</h1><table><thead><tr><th>ID</th><th>图片</th><th>产品</th><th>创建订单</th><th>RTS金额(USD)</th></tr></thead><tbody>'+rows.map(function(p){return '<tr><td>'+esc(p.product_id)+'</td><td>'+(p.main_image?'<img width="100" src="'+esc(p.main_image)+'">':'')+'</td><td>'+esc(p.title)+'</td><td>'+num(p.orders)+'</td><td>'+num(p.gmv)+'</td></tr>';}).join('')+'</tbody></table></html>';_downloadHTML(rankingFilename('selected_new')+'.html',html);}
renderNewSelected=function(m){return rankingToolbar('boss_selected',newSelectionRows(),'已选新品')+auditOriginalNewSelected(m);};
var auditOriginalBossInteractions=initBossInteractions;
initBossInteractions=function(){auditOriginalBossInteractions();var box=document.getElementById('bossNewPoolBody');if(!box){var search=document.getElementById('bossNewSearch');box=search&&search.parentElement;}if(box&&!box.querySelector('.audit-export'))box.insertAdjacentHTML('afterbegin',rankingToolbar('boss_pool',(D.boss||{}).product_pool||[],'新品候选产品池'));};
var auditOriginalNewManager=openNewManager;
openNewManager=function(){auditOriginalNewManager();var box=document.getElementById('npModal');if(box)box.querySelector('div').insertAdjacentHTML('afterbegin',rankingToolbar('new_manager',D.new_candidates||[],'管理新品候选'));};
var auditOriginalMarket=renderMarket;
renderMarket=function(){var h=auditOriginalMarket();var rows=(D.v4_sections||{}).hot_products_clean||[];return h.replace('<div class="card">','<div class="card">'+weeklyOnlyNote()+rankingToolbar('market_products',rows,'行业热品（外部产品）'));};
var auditOriginalSummary=renderSummary;
renderSummary=function(){var h=auditOriginalSummary();h=h.replace(/<div class="tbl-scroll"><table><thead><tr><th>#<\/th><th>市场热销品[\s\S]*?<\/table><\/div>/,'<p class="muted small">市场热品明细与“市场机会”共用同一清单，保留查看与导出入口。</p>');return h.replace('<div class="card">','<div class="card">'+weeklyOnlyNote()+rankingToolbar('summary_market',(D.v4_sections||{}).hot_products_clean||[],'市场热品参考'));};

function renderProdTrend(pid){var box=document.getElementById('prodTrend');if(!box)return;var p=(auditPeriod().products||[]).find(function(x){return x.product_id===pid;});if(!p){box.innerHTML='<p class="muted">所选期间无该产品明细。</p>';return;}var fields=[['全店曝光',p.total_imps],['全店点击',p.total_clk],['询盘',p.inquiries],['TM',p.tm],['询盘+TM（未去重）',p.opp],['广告点击',p.ad_clk],['创建订单(crtOrd)',p.orders],['RTS金额(USD)',p.gmv]];box.innerHTML='<h4>'+esc(p.title)+' · '+esc(bossPeriodLabel())+'</h4><table><thead><tr><th>指标</th><th>值</th></tr></thead><tbody>'+fields.map(function(r){return '<tr><td>'+r[0]+'</td><td>'+num(r[1])+'</td></tr>';}).join('')+'</tbody></table><p class="muted small">单品花费与广告归因未提供；不能把广告点击解释为烧钱或零成本。</p>';}
function auditSummaryRows(){
  var b=D.boss||{},m=getBossManual(),sp=b.spend||{},k=b.kpi||{};
  var ad=m.ad_spend_override!=null&&m.ad_spend_override!==''?Number(m.ad_spend_override):sp.ad_spend;
  var other=auditOtherSpend(m),sum=auditSum(ad,other),acq=auditNumber(m.acquisition);
  var cac=m.cac!=null&&m.cac!==''?Number(m.cac):acq>0&&sum!=null?sum/acq:null;
  var rows=[['广告花费',ad,'CNY','手动或广告账户'],['其他花费',other,'CNY','手动，全部分项填写后求和'],['店铺总花费',sum,'CNY','广告+其他，缺值不求和'],['获客数量',acq,'人','手动'],['优质获客',m.quality_customers,'人','手动'],['获客成本',cac,'CNY','手动或总花费/获客'],['广告CPL',sp.ad_cpl,'CNY','广告账户'],['样品单',m.sample_orders,'单','手动'],['新品数',m.new_count,'款','手动']];
  getFunnel().forEach(function(f){rows.push([f.label,f.cur,f.key==='suc_ord_amt'?'USD':f.fmt==='pct'?'%':f.unit||'次',f.note||'经营总览接口']);});
  rows.push(['平台abCnt',auditPeriod().period.platform_ab_cnt,'平台字段','不等同询盘+TM加总']);
  rows.push(['创建订单',auditPeriod().period.created_orders,'单','crtOrdCnt；不等同成交订单']);
  return rows;
}
function exportCSV(view){var rows=[['店铺','期间','指标','值','单位','来源/口径']];auditSummaryRows().forEach(function(r){rows.push([D.meta.store_name,bossPeriodLabel()].concat(r));});downloadRankingFile(rankingFilename(view||'overview')+'.csv','\uFEFF'+rows.map(function(r){return r.map(csvSafe).join(',');}).join('\r\n'),'text/csv;charset=utf-8;');}
function buildReportHTML(view){var rows=auditSummaryRows();return '<!DOCTYPE html><html lang="zh"><meta charset="utf-8"><title>'+esc(D.meta.store_name)+' 经营数据</title><style>body{font:15px system-ui;max-width:1100px;margin:32px auto;padding:16px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:9px;text-align:left}</style><h1>'+esc(D.meta.store_name)+' · '+esc(bossPeriodLabel())+'</h1>'+auditBanner()+'<p>缺失值表示未提供或未填写；不会转换为0。</p><table><thead><tr><th>指标</th><th>值</th><th>单位</th><th>来源/口径</th></tr></thead><tbody>'+rows.map(function(r){return '<tr>'+r.map(function(v){return '<td>'+esc(v==null?'未提供 / 未填写':v)+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table></html>';}
async function exportXLSX(view){
  if(typeof ExcelJS==='undefined'){exportCSV(view);return;}
  try{var book=new ExcelJS.Workbook(),sheet=book.addWorksheet('经营数据');sheet.addRow(['店铺',D.meta.store_name,'期间',bossPeriodLabel()]);sheet.addRow(['指标','值','单位','来源/口径']);auditSummaryRows().forEach(function(r){sheet.addRow(r);});sheet.columns=[{width:26},{width:24},{width:14},{width:80}];sheet.getRow(2).font={bold:true};sheet.views=[{state:'frozen',ySplit:2}];_downloadXLSX(rankingFilename(view||'overview')+'.xlsx',await book.xlsx.writeBuffer());}catch(e){alert('Excel导出失败，可使用CSV：'+e.message);}
}
var auditOriginalAd=renderAd;
renderAd=function(){
  var a=auditPeriod(),s=(a.boss||{}).spend||{},rows=a.ad_products||[];
  var h='<div class="section-title">广告账户与产品点击</div><div class="card"><p>账户花费(CNY)：'+_m(s.ad_spend)+' · 点击 '+_n(s.ad_clicks)+' · 曝光 '+_n(s.ad_imps)+' · CPL '+_m(s.ad_cpl)+'</p><p class="muted small">账户汇总与经营总览为不同报表口径；空列表表示数据未提供。单品广告点击与全店商机同时存在，不证明广告归因或低耗。</p>'+rankingToolbar('ad_products',rows,'产品广告点击榜')+'<table><thead><tr><th>产品ID</th><th>产品</th><th>广告曝光</th><th>广告点击</th></tr></thead><tbody>';
  rows.slice(0,20).forEach(function(p){h+='<tr><td>'+esc(p.product_id)+'</td><td>'+plink(p)+'</td><td>'+num(p.ad_imps)+'</td><td>'+num(p.ad_clk)+'</td></tr>';});return h+'</tbody></table><p class="muted small">表内预览前20项，查看全部及导出包含全部 '+rows.length+' 项。</p></div>';
};
var auditOriginalRefresh=refreshAllPanels;
refreshAllPanels=function(){syncAuditPeriod();auditOriginalRefresh();attachAuxiliaryExports();};
var auditOriginalPopulatePeriod=populatePeriodSel;
populatePeriodSel=function(){auditOriginalPopulatePeriod();var s=document.getElementById('weekSel'),a=PERIOD==='month'?D.months:D.weeks,i=PERIOD==='month'?SELECTED_MONTH:SELECTED_WEEK;if(s)s.value=i<0?a.length-1:i;};
var auditOriginalBoot=boot;
boot=function(){syncAuditPeriod();auditOriginalBoot();attachAuxiliaryExports();};
// Keep metadata dates stable for the shared index; all visible labels use the selection.
syncAuditPeriod();
document.addEventListener('DOMContentLoaded',function(){attachAuxiliaryExports();});





