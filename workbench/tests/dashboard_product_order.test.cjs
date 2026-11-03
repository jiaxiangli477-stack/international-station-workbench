const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('dashboard_product_order.js','utf8');
function load(){
  const products=[
    {product_id:'empty'},
    {product_id:'imps',total_imps:10000,total_clk:0,inquiries:0,tm:null,orders:0},
    {product_id:'clicks',total_imps:300,total_clk:50,inquiries:0,tm:0,orders:0},
    {product_id:'inquiry',total_clk:3,inquiries:2,tm_daily_sum:1,tm:null,orders:null},
    {product_id:'tm',total_clk:8,inquiries:0,tm_daily_sum:4,orders:0},
    {product_id:'order',orders:1,total_clk:1,inquiries:0,tm:0},
    {product_id:'zero',orders:0,inquiries:0,tm:0,total_clk:0,total_imps:0}
  ];
  const raw={products,lists:{opp:products,ctr:products,state_grid:[{state:'x',items:products}]},boss:{product_pool:products,hot_products:products,manual:{new_selection:['tm','order']}}};
  let selected,current=raw;
  const s={window:{},document:{getElementById(){return null}},D:{boss:raw.boss},auditPeriod:()=>current,getLists:()=>current.lists,
    renderNewSelected(m){selected=m.new_selection;return selected.join(',')},rankingFilter:()=>products,rankingToolbar(k,rows){return rows},exportRankingCSV(k,rows){return rows},
    renderBoss(){},renderPeriod(){},syncAuditPeriod(){s.D.boss=s.auditPeriod().boss;}};
  vm.createContext(s);vm.runInContext(source,s);return {s,raw,products,selected:()=>selected,setPeriod:p=>{current=p;s.syncAuditPeriod();}};
}
const ids=a=>Array.from(a,p=>p.product_id);
test('inquiries then clicks then impressions govern every product order',()=>{const {s}=load();assert.deepEqual(ids(s.auditPeriod().products),['inquiry','clicks','tm','order','imps','zero','empty']);});
test('sorting never mutates source periods, values or original pool order',()=>{const {s,raw,products}=load();const before=JSON.stringify(raw);s.renderBoss();s.getLists();assert.equal(JSON.stringify(raw),before);assert.equal(products[0].product_id,'empty');assert.equal(products[3].tm,null);});
test('boss platform groups and new-product pool use the same order',()=>{const {s}=load();assert.deepEqual(ids(s.D.boss.product_pool),ids(s.auditPeriod().products));assert.deepEqual(ids(s.D.boss.hot_products),ids(s.auditPeriod().products));});
test('CTR TM and opportunity lists cannot override inquiry priority',()=>{const {s}=load();const sort=s.window.dashboardProductOrder.sort;const rows=[{product_id:'a',orders:100,total_ctr:90,tm_daily_sum:99,opp:100,inquiries:1},{product_id:'b',orders:0,total_ctr:1,tm_daily_sum:0,opp:5,inquiries:5},{product_id:'c',inquiries:null}];for(const key of ['ctr','tm','opp','inquiry'])assert.deepEqual(ids(sort(rows,key)),['b','a','c']);});
test('clicks break inquiry ties, exposure breaks click ties, TM never changes order',()=>{const {s}=load();const rows=[{product_id:'a',inquiries:2,total_clk:3,total_imps:99,tm_daily_sum:900},{product_id:'b',inquiries:2,total_clk:4,total_imps:1},{product_id:'c',inquiries:2,total_clk:4,total_imps:20}];assert.deepEqual(ids(s.window.dashboardProductOrder.sort(rows)),['c','b','a']);});
test('selected preview is ordered without mutating saved selection',()=>{const {s}=load();const manual={new_selection:['order','tm']};assert.equal(s.renderNewSelected(manual),'tm,order');assert.deepEqual(manual.new_selection,['order','tm']);});
test('exports and every ranking key use the shared order and preserve original IDs',()=>{const {s}=load();for(const key of ['boss_pool','list_ctr','list_tm','ai','new_tracking','custom'])assert.deepEqual(ids(s.rankingFilter(key)),ids(s.D.boss.product_pool));const rows=[{product_id:'000000000000001',inquiries:1},{product_id:'90000000000000000001',inquiries:2}];assert.deepEqual(ids(s.exportRankingCSV('x',rows)),['90000000000000000001','000000000000001']);});
test('changing selected period changes ordering instead of retaining prior products',()=>{const {s,setPeriod}=load();setPeriod({products:[{product_id:'low',inquiries:0,total_clk:1},{product_id:'new',inquiries:7}],boss:{product_pool:[]},lists:{}});assert.deepEqual(ids(s.auditPeriod().products),['new','low']);assert(!s.auditPeriod().products.some(p=>p.product_id==='order'));});
