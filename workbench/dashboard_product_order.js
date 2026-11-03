/* DASHBOARD_PRODUCT_ORDER_V1: display order only; retain source values and AI scores. */
(function(){
  if(window.__dashboardProductOrderV1)return;
  window.__dashboardProductOrderV1=true;
  function value(p,keys){
    for(var i=0;i<keys.length;i++){
      var x=p[keys[i]];
      if(x!=null&&x!==''&&typeof x!=='boolean'&&Number.isFinite(Number(x)))return Number(x);
    }
    return null;
  }
  function metrics(p){
    return [value(p,['inquiries']),value(p,['total_clk','clicks','ad_clk']),value(p,['total_imps','imps','impressions','ad_imps'])];
  }
  function descending(a,b){return a==null?(b==null?0:1):(b==null?-1:b-a);}
  function compare(a,b){
    var am=metrics(a),bm=metrics(b),diff;
    for(var i=0;i<am.length;i++){diff=descending(am[i],bm[i]);if(diff)return diff;}
    return String(a.product_id||'').localeCompare(String(b.product_id||''));
  }
  function ordered(rows,key){
    return (rows||[]).slice().sort(compare);
  }
  function lists(base){
    var out=Object.assign({},base);
    Object.keys(out).forEach(function(k){
      if(k==='state_grid')out[k]=(out[k]||[]).map(function(g){return Object.assign({},g,{items:ordered(g.items)});});
      else if(Array.isArray(out[k]))out[k]=ordered(out[k],k);
    });
    return out;
  }
  function boss(base){
    if(!base)return base;
    var out=Object.assign({},base);
    ['hot_products','premium_products','potential_products','new_products','product_pool','product_pool_month'].forEach(function(k){if(Array.isArray(out[k]))out[k]=ordered(out[k]);});
    return out;
  }
  var cache=new WeakMap(),sourcePeriod=auditPeriod;
  auditPeriod=function(){
    var a=sourcePeriod.apply(this,arguments);
    if(!a||typeof a!=='object')return a;
    if(!cache.has(a))cache.set(a,Object.assign({},a,{products:ordered(a.products),lists:lists(a.lists),boss:boss(a.boss)}));
    return cache.get(a);
  };
  var sourceLists=getLists;
  getLists=function(){return lists(sourceLists.apply(this,arguments));};
  var sourceSelected=renderNewSelected;
  renderNewSelected=function(m){
    var copy=Object.assign({},m),ids=new Set((m.new_selection||[]).map(String));
    copy.new_selection=ordered((D.boss||{}).product_pool||[]).filter(function(p){return ids.has(String(p.product_id));}).map(function(p){return p.product_id;});
    return sourceSelected.call(this,copy);
  };
  var sourceFilter=rankingFilter;
  rankingFilter=function(key){
    return ordered(sourceFilter.apply(this,arguments));
  };
  var sourceToolbar=rankingToolbar;
  rankingToolbar=function(key,rows,label){return sourceToolbar.call(this,key,ordered(rows),label);};
  var sourceCSV=exportRankingCSV;
  exportRankingCSV=function(key,rows){return sourceCSV.call(this,key,ordered(rows||rankingFilter(key)));};
  if(typeof dAdRows==='function'){
    var sourceAdRows=dAdRows;
    dAdRows=function(){return ordered(sourceAdRows.apply(this,arguments));};
  }
  function note(id){
    var el=document.getElementById(id);if(!el||el.querySelector('.product-order-note'))return;
    var head=el.querySelector('.boss-head, .section-title');
    if(head)head.insertAdjacentHTML('afterend','<p class="muted small product-order-note">所有产品榜单统一排序：询盘数量降序 → 点击量降序 → 曝光量降序；前项相同时比较后一项，缺失值排后。同值按产品ID稳定排列。</p>');
  }
  var sourceBoss=renderBoss;
  renderBoss=function(){D.boss=boss(D.boss);var result=sourceBoss.apply(this,arguments);note('panel-boss');return result;};
  var sourceRenderPeriod=renderPeriod;
  renderPeriod=function(){var result=sourceRenderPeriod.apply(this,arguments);note('panel-period');return result;};
  window.dashboardProductOrder={sort:ordered,compare:compare};
  syncAuditPeriod();
})();
