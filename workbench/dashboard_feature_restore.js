/* DASHBOARD_FEATURE_RESTORE_V1: keep exports and panels; qualify unavailable metrics. */
(function(){
  if(window.__dashboardFeatureRestoreV1)return;
  window.__dashboardFeatureRestoreV1=true;
  function daily(){return (auditPeriod().provenance||{}).mode==='daily_rollup';}
  function numeric(v){return v==null||v===''||!Number.isFinite(Number(v))?null:Number(v);}
  function signalRow(p){
    var inquiry=numeric(p.inquiries),tm=numeric(p.tm_daily_sum);
    var present=(inquiry>0||tm>0)?true:(inquiry===0&&tm===0)?false:null;
    return Object.assign({},p,{tm_weekly_unique:p.tm,opp_weekly_original:p.opp,
      tm:tm,opp:inquiry!=null&&tm!=null?inquiry+tm:null,signal_present:present,
      display_metric_basis:'daily_signal_not_unique',label:present===true?'有日累计沟通信号':present===false?'日累计沟通信号为0':'部分指标待核对',label_typ:present===true?'good':'neutral'});
  }
  var originalLists=getLists;
  getLists=function(){
    var base=originalLists();if(!daily())return base;
    var rows=(auditPeriod().products||[]).map(signalRow),sort=function(a,b){return (b.opp||0)-(a.opp||0);};
    return Object.assign({},base,{
      inquiry:rows.filter(function(p){return p.inquiries>0;}).sort(function(a,b){return b.inquiries-a.inquiries;}),
      opp:rows.filter(function(p){return p.signal_present===true;}).sort(sort),
      tm:rows.filter(function(p){return p.tm>0&&p.inquiries===0;}).sort(function(a,b){return b.tm-a.tm;}),
      zero_cost:rows.filter(function(p){return p.ad_clk===0&&(p.signal_present===true||p.total_clk>=4);}).sort(sort),
      high_eff_low_cost:rows.filter(function(p){return p.ad_clk>0&&p.signal_present===true;}).sort(sort)
    });
  };
  var sourceRankingFilter=rankingFilter;
  rankingFilter=function(key){
    if(key==='boss_selected')return rankingRows(newSelectionRows());
    if(key==='boss_pool'){
      var query=((document.getElementById('bossNewSearch')||{}).value||'').toLowerCase();
      return rankingRows((D.boss||{}).product_pool||[]).filter(function(p){return !query||((p.title||'')+' '+p.product_id).toLowerCase().includes(query);});
    }
    var mapping={zero:'zero_cost',eff:'high_eff_low_cost',opp:'opp',tm:'tm',ctr:'ctr'};
    if(key.indexOf('list_')===0&&mapping[key.slice(5)]){
      var note=key.slice(5),field=(document.getElementById('filter_'+note)||{}).value||'';
      return rankingRows(getLists()[mapping[note]]||[]).filter(function(p){return !field||p.category===field;});
    }
    return sourceRankingFilter(key);
  };
  var listRenderer=typeof dailyListOriginal==='function'?dailyListOriginal:renderList;
  renderList=function(title,sub,key,noteKey){
    var html=listRenderer.apply(this,arguments);
    if(daily()){
      html=html.replace(/(<th[^>]*>)商机(<\/th>)/g,'$1沟通信号（日累计）$2').replace(/(<th[^>]*>)TM(<\/th>)/g,'$1TM（日累计）$2');
      html=html.replace('<div class="card">','<div class="card"><p class="muted small">询盘及TM为日累计沟通信号（未去重），不代表自然周独立买家；未知项留空。无广告点击不等于零花费。</p>');
    }
    return html;
  };
  var originalCSV=exportRankingCSV;
  exportRankingCSV=function(key,rows){
    rows=rows||rankingFilter(key);
    if(!daily()||!rows.some(function(p){return p.display_metric_basis==='daily_signal_not_unique';}))return originalCSV(key,rows);
    var fields=['product_id','title','category','total_imps','total_clk','inquiries','tm','opp','orders','gmv','observation_days','tm_weekly_unique'];
    var labels=['product_id','title','category','impressions_daily_sum','clicks_daily_sum','inquiries_daily_sum','TM_daily_sum_not_unique','contact_signal_daily_sum_not_unique','created_orders_daily_sum','rtsOnlineAmt_USD_daily_sum','observed_days_out_of_7','TM_weekly_unique_unavailable'];
    var lines=[['期间','排名'].concat(labels).map(csvSafe).join(',')];
    rankingRows(rows).forEach(function(p,i){lines.push([bossPeriodLabel(),i+1].concat(fields.map(function(k){return p[k];})).map(csvSafe).join(','));});
    downloadRankingFile(rankingFilename(key)+'.csv','\uFEFF'+lines.join('\r\n'),'text/csv;charset=utf-8;');
  };
  var sourceSelectedRows=newSelectionRows;
  newSelectionRows=function(){
    if(typeof getBossManual!=='function'||!D.boss||!Array.isArray(D.boss.product_pool))return sourceSelectedRows();
    var ids=new Set((getBossManual().new_selection||[]).map(String));
    return rankingRows(D.boss.product_pool.filter(function(p){return (typeof p.product_id!=='number'||Number.isSafeInteger(p.product_id))&&ids.has(String(p.product_id));}).map(function(p){return Object.assign({},p,{product_id:String(p.product_id)});}));
  };
  function selected(){return rankingRows(newSelectionRows());}
  function display(v){return v==null||v===''?'—':esc(String(v));}
  function safeURL(v){var u=String(v||'');if(u.indexOf('//')===0)u='https:'+u;return /^https?:\/\/[^\s<>"']+$/.test(u)?u:'';}
  function newDocument(rows){
    var title=(D.meta.store_name||'店铺')+' · 新品清单 · '+bossPeriodLabel();
    var h='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>body{font:14px system-ui,sans-serif;color:#233044;margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #dce2ea;padding:8px;text-align:left;vertical-align:middle}th{background:#f3f6fa}img{width:100px;height:100px;object-fit:contain}small{color:#68788b}@media print{body{margin:8mm}tr{break-inside:avoid}}</style></head><body><h1>'+esc(title)+'</h1><p>已选 '+rows.length+' 个产品；ID按原始字符串保留。图片、名称、层级与表现均来自当前所选期间。</p>';
    if(daily())h+='<p><small>产品曝光、点击、询盘、订单及金额为按日累计；TM日累计非周去重。未知值显示—，不补0。</small></p>';
    h+='<table><thead><tr><th>图片</th><th>产品名称 / 链接</th><th>产品ID</th><th>层级</th><th>曝光</th><th>点击</th><th>CTR</th><th>询盘'+(daily()?'（日累计）':'')+'</th><th>TM'+(daily()?'（日累计未去重）':'')+'</th><th>创建订单</th><th>RTS金额(USD)</th></tr></thead><tbody>';
    rows.forEach(function(p){var img=safeURL(p.main_image),url=safeURL(p.detail_url)||safeURL(pUrl(p));
      h+='<tr><td>'+(img?'<img src="'+esc(img)+'" alt="'+esc(p.title||'')+'">':'—')+'</td><td>'+(url?'<a href="'+esc(url)+'" target="_blank" rel="noopener">'+esc(p.title||'')+'</a>':esc(p.title||''))+'</td><td>'+esc(String(p.product_id))+'</td><td>'+esc(p.level||p.prod_level||'未提供')+'</td><td>'+display(p.total_imps==null?p.imps:p.total_imps)+'</td><td>'+display(p.total_clk==null?p.clicks:p.total_clk)+'</td><td>'+display(p.total_ctr==null?null:p.total_ctr+'%')+'</td><td>'+display(p.inquiries)+'</td><td>'+display(daily()?p.tm_daily_sum:p.tm)+'</td><td>'+display(p.orders)+'</td><td>'+display(p.gmv)+'</td></tr>';
    });return h+'</tbody></table></body></html>';
  }
  window.buildSelectedNewProductHTML=newDocument;
  exportNewSelection=function(){var rows=selected();if(!rows.length){alert('请先在产品池点选具体新品，再导出。');return;} _downloadHTML(rankingFilename('selected_new')+'.html',newDocument(rows));};
  function attach(){
    var sec=document.getElementById('bossNewSec');if(!sec)return;
    var bar=document.getElementById('bossNewExportActions');
    if(!bar){
      var head=sec.querySelector('h3');if(!head)return;
      head.insertAdjacentHTML('afterend','<div id="bossNewExportActions" class="flex mb8" style="gap:8px;flex-wrap:wrap"><button type="button" class="btn" id="selectedNewIds">导出新品ID / 查看全部</button><button type="button" class="btn" id="selectedNewCSV">导出新品CSV</button><button type="button" class="btn" id="selectedNewHTML">导出新品清单（带图HTML）</button><span class="muted small" id="selectedNewExportCount"></span></div>');
      document.getElementById('selectedNewIds').onclick=function(){rankingToolbar('boss_selected',selected(),'已选新品');openRankingExport('boss_selected');};
      document.getElementById('selectedNewCSV').onclick=function(){rankingToolbar('boss_selected',selected(),'已选新品');exportRankingCSV('boss_selected',selected());};
      document.getElementById('selectedNewHTML').onclick=function(){exportNewSelection();};
    }
    var count=document.getElementById('selectedNewExportCount');if(count)count.textContent='当前期间已选 '+selected().length+' 个；手填新品数量不代替具体产品ID';
  }
  var originalBoss=renderBoss;renderBoss=function(){var value=originalBoss.apply(this,arguments);attach();return value;};
  var originalSelected=renderNewSelected;renderNewSelected=function(){var value=originalSelected.apply(this,arguments);setTimeout(attach,0);return value;};
  document.addEventListener('DOMContentLoaded',attach);
})();
