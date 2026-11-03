const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const feature=fs.readFileSync('dashboard_feature_restore.js','utf8');
function load(){
  const rows=[
    {product_id:'000123456789012345678',title:'Honey <test>',category:'蜂蜜',main_image:'https://example.com/honey.jpg',inquiries:1,tm:null,tm_daily_sum:3,opp:null,ad_clk:0,total_clk:5,total_imps:100,orders:0,gmv:0},
    {product_id:'2',inquiries:0,tm:null,tm_daily_sum:2,opp:null,ad_clk:2,total_clk:4,total_imps:100},
    {product_id:'3',inquiries:null,tm:null,tm_daily_sum:null,opp:null,ad_clk:2,total_clk:4,total_imps:100},
    {product_id:'4',inquiries:0,tm:null,tm_daily_sum:0,opp:null,ad_clk:0,total_clk:4,total_imps:100}
  ];
  const p={provenance:{mode:'daily_rollup'},products:rows};
  const s={window:{},document:{addEventListener(){},getElementById(){return null}},setTimeout(){},alert(){},D:{meta:{store_name:'Test store'}},
    auditPeriod:()=>p,getLists:()=>({state_grid:[]}),renderList:()=>'<div class="card"><select></select><table><th>商机</th></table></div>',
    dailyListOriginal:()=>'<div class="card"><button>导出ID</button><select></select><table><th>商机</th></table></div>',
    exportRankingCSV(){},rankingFilter:()=>[],rankingRows:r=>Array.from(new Map(r.map(p=>[p.product_id,p])).values()),
    csvSafe:v=>'"'+String(v??'').replace(/"/g,'""')+'"',bossPeriodLabel:()=> '2026-10-05 ~ 2026-10-11',rankingFilename:()=> 'period',
    newSelectionRows:()=>[rows[0]],esc:v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'),
    pUrl:p=>'https://www.alibaba.com/product-detail/'+p.product_id+'.html',exportNewSelection(){},renderBoss(){},renderNewSelected:()=>'',
    _downloadHTML:(name,text)=>{s.download={name,text};},downloadRankingFile:(name,text)=>{s.download={name,text};}};
  vm.createContext(s);vm.runInContext(feature,s);return {s,p,rows};
}
test('all four signal panels retain tables, filters and ID exports',()=>{const {s}=load();for(const key of ['zero_cost','high_eff_low_cost','opp','tm']){const html=s.renderList(key,'',key,key);assert.match(html,/<table>/);assert.match(html,/<select>/);assert.match(html,/导出ID/);assert.match(html,/日累计/);assert.doesNotMatch(html,/不可计算：/);}});
test('positive daily TM identifies products without pretending to know weekly uniques',()=>{const {s,rows}=load(),lists=s.getLists();assert.equal(lists.opp.length,2);assert.equal(lists.tm.length,1);assert.equal(lists.zero_cost.length,2);assert.equal(lists.high_eff_low_cost.length,1);assert.equal(rows[0].tm,null);assert.equal(rows[0].opp,null);assert.equal(lists.opp[0].opp,4);assert.equal(lists.opp[0].tm_weekly_unique,null);assert(!lists.opp.some(p=>p.product_id==='3'));});
test('signal CSV labels the actual daily quantities and keeps long original IDs',()=>{const {s}=load();s.exportRankingCSV('signal',s.getLists().opp);assert.match(s.download.text,/contact_signal_daily_sum_not_unique/);assert.match(s.download.text,/TM_weekly_unique_unavailable/);assert.match(s.download.text,/000123456789012345678/);});
test('selected new-product exporter creates a standalone illustrated HTML',()=>{const {s}=load();s.exportNewSelection();assert.match(s.download.name,/\.html$/);assert.match(s.download.text,/000123456789012345678/);assert.match(s.download.text,/<img/);assert.match(s.download.text,/honey\.jpg/);assert.match(s.download.text,/Honey &lt;test&gt;/);assert.match(s.download.text,/RTS金额\(USD\)/);assert.match(s.download.text,/2026-10-05 ~ 2026-10-11/);});
test('legacy month lists are preserved',()=>{const {s,p}=load();p.provenance={};assert.equal(s.getLists().state_grid.length,0);assert.equal(s.getLists().opp,undefined);});
test('restoration is idempotent',()=>{const {s}=load(),first=s.getLists;vm.runInContext(feature,s);assert.equal(s.getLists,first);});
test('list ID exports follow current data even when the old export registry is empty',()=>{const {s}=load();assert.equal(s.rankingFilter('list_opp').length,2);assert.equal(s.rankingFilter('list_tm').length,1);});
test('selected IDs are matched as strings against the current product pool',()=>{const {s,rows}=load();s.D.boss={product_pool:rows};s.getBossManual=()=>({new_selection:['000123456789012345678']});assert.equal(s.newSelectionRows().length,1);s.exportNewSelection();assert.match(s.download.text,/000123456789012345678/);});
test('new-product toolbar is always present in the implementation, not hidden by zero selection',()=>{assert.match(feature,/id="selectedNewIds"/);assert.match(feature,/id="selectedNewHTML"/);assert.match(feature,/id="selectedNewCSV"/);assert.match(feature,/head\.insertAdjacentHTML\('afterend'/);});
