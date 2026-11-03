const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const runtime=fs.readFileSync('dashboard_integrity_runtime.js','utf8');
function load(){
  const period={week_start:'2026-10-18',week_end:'2026-10-24',uv_payord_rate:0,uv_cnt:1107,suc_byr_cnt:3,valid_prod_cnt:456};
  const health={valid_cnt:430,inquiry_products:9,zero_inquiry:421,levels:[{label:'爆品',count:2},{label:'优品',count:159},{label:'潜力优品',count:220}]};
  const bundle={period,health,products:[],lists:{},boss:{spend:{}}};
  const saved=new Map([['v4note_health','用户原备注，不覆盖']]);
  const s={D:{meta:{week_label:'2026-10-18 ~ 2026-10-24'},weeks:[period],months:[],audit_periods:{'week:2026-10-18':bundle},section_notes:{health:'旧的0产品摘要',staff:'共0名子账号在接待'},staff_cs:[]},
    PERIOD:'week',SELECTED_WEEK:-1,SELECTED_MONTH:-1,window:{},document:{addEventListener(){},getElementById(){return null;}},
    localStorage:{getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v)},
    num:v=>v==null?'—':String(v),pct:v=>v==null?'—':Number(v).toFixed(2)+'%',esc:v=>String(v??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),
    weekToFunnel:p=>[{key:'uv_payord_rate',cur:p.uv_payord_rate,fmt:'pct'}],monthToFunnel:p=>[{key:'uv_payord_rate',cur:p.uv_payord_rate,fmt:'pct'}]};
  for(const m of runtime.matchAll(/var auditOriginal\w+=(\w+);/g))s[m[1]]=()=>'';
  vm.createContext(s);vm.runInContext(runtime,s);return {s,bundle,saved};
}
test('default health note follows selected product counts and separates store count',()=>{
  const {s,bundle}=load();assert.match(s.D.section_notes.health,/爆品 2/);assert.match(s.D.section_notes.health,/优品 159/);assert.match(s.D.section_notes.health,/产品明细 430/);assert.match(s.D.section_notes.health,/店铺有效商品 456/);
  bundle.health={valid_cnt:null,levels:[],zero_inquiry:null};s.syncAuditPeriod();assert.match(s.D.section_notes.health,/未采集/);assert.doesNotMatch(s.D.section_notes.health,/产品明细 430/);
});
test('default-note refresh never writes or replaces persisted user notes',()=>{
  const {s,saved}=load();s.syncAuditPeriod();assert.equal(saved.size,1);assert.equal(saved.get('v4note_health'),'用户原备注，不覆盖');
});
test('missing selected-period staff is not reported as zero staff',()=>{
  const {s}=load();assert.match(s.D.section_notes.staff,/未匹配/);assert.doesNotMatch(s.D.section_notes.staff,/共0名/);
});
test('star prediction selects platform track and does not call lower prediction preservation',()=>{
  const {s}=load(),sr={stat_date:'2026-10-24',level_star:5,display_star:2,predict_track_type:'rts',tracks:[{track_type:'custom',track_name:'商机赛道',star:3,alert:{down:false}},{track_type:'rts',track_name:'交易赛道',star:2,alert:{down:false}}]};
  assert.equal(s.auditStarTrack(sr).track_type,'rts');const html=s.auditStarPredictionHTML(sr);assert.match(html,/平台预测2星/);assert.match(html,/交易赛道/);assert.match(html,/danger/);assert.doesNotMatch(html,/预测保星/);
  sr.display_star=null;sr.tracks[1].star=null;assert.match(s.auditStarPredictionHTML(sr),/未提供/);assert.doesNotMatch(s.auditStarPredictionHTML(sr),/保星/);
});
test('raw zero conversion rate remains zero with a source-definition disclosure',()=>{
  const {s}=load(),row=s.getFunnel().find(x=>x.key==='uv_payord_rate');assert.equal(row.cur,0);assert.match(row.note,/uvPayordRate/);assert.match(row.note,/不以成交买家/);
});
