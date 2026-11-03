const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
function screen(){
 const c={URL,URLSearchParams,Set,Map,console,esc:x=>String(x??''),head:()=>'',icon:()=>'',
  document:{addEventListener(){},getElementById(){return null}},window:{addEventListener(){}},
  location:{hash:'#workproduct?item=p'},teamViewOnly:()=>false,integrationDate:x=>x||'—',
  modulePage:()=>'',selectionPage:()=>'',hubPreviewProducts(){},topicStore:'youhealth',topicBusy:false,
  topicData:{records:[{id:'r',title:'Powder',categories:[],capabilities:[],requirements:[],pictureMatch:'Y'}]},openDrawer:html=>{c.drawer=html}};
 vm.createContext(c);
 for(const file of ['execution_ui.js','production_ui.js','recruitment_ui.js'])vm.runInContext(fs.readFileSync(file,'utf8'),c);
 vm.runInContext(`executionData={products:[{id:'p',title:'Powder',revision:5,stage:'VISUAL_REVIEW',facts:{mode:'concept'},events:[],references:[],workflow:{approvalPolicy:'single-hero-v1',status:'VISUALS_READY'},visual:{revision:5,job:'images',templateCount:18,images:productionSlotsLatest.map(slot=>({slot,file:slot+'.png',specCheck:'ok'}))}}],jobs:[],stores:[]}`,c);
 return c;
}
test('both production workspaces visibly describe Skill reuse, one hero review and local execution',()=>{
 const c=screen();for(const kind of ['images','listing']){const html=c.productionWorkspace(kind);assert.match(html,/原 Skill 优先生成产品资料/);assert.match(html,/无需先手填全部资料/);assert.match(html,/新任务仅确认正式首图 m1/);assert.match(html,/异常由系统列明/);assert.match(html,/自行发布/);assert.match(html,/当前在本机执行/);assert.match(html,/服务器后续再接/);}
});
test('current 18-image output is preserved and rendering does not change records',()=>{
 const c=screen(),before=vm.runInContext('JSON.stringify(executionData)',c);const html=c.workproductPage();assert.match(html,/已生成 18\/18/);assert.match(html,/优先复用当前版本已完成的套图/);assert.match(html,/未核实内容保留待核验/);assert.doesNotMatch(html,/不可直接上品|转入上品前必须确认真实配方/);assert.equal(vm.runInContext('JSON.stringify(executionData)',c),before);
});
test('selection handoff routes to Skill-prepared data without requiring all facts first',()=>{
 const html=screen().selectionHandoffPanel();assert.match(html,/由原 Skill 优先生成和复用产品资料/);assert.doesNotMatch(html,/确认产品资料后再调用/);
});
test('recruitment list and detail distinguish visual matching from authoritative platform success',()=>{
 const c=screen(),list=c.demandsPage();assert.match(list,/商品主体、剂型和包装形式相近/);assert.match(list,/主图相近不代表平台征品通过/);assert.match(list,/报名状态以平台回读为准/);
 c.topicDetail('r');assert.match(c.drawer,/原 Skill 优先生成产品资料并复用已有方案与图片/);assert.match(c.drawer,/新任务只确认正式首图 m1/);assert.match(c.drawer,/成功征品和报名状态仍须平台回读/);
});

test('saved-draft UI exposes explicit original-Skill completion and never equates sparse readback with full coverage',()=>{
 const c=screen();const p={id:'p',revision:5,facts:{store:'youhealth'},workflow:{listingMechanism:'original-skill-v1'},draft:{draft_id:'123',readback_verified:true,fields:{}}};
 const pending=c.productionReceipt(p);assert.match(pending,/flow-listing-complete/);assert.match(pending,/历史非空字段回读不代表所有属性已填完/);
 p.draft.content_readback_verified=true;p.draft.content_coverage={ordinaryFilled:16,customAttributes:10,faqs:8,sellingPoints:5};
 const done=c.productionReceipt(p);assert.match(done,/自定义属性 10\/10/);assert.match(done,/FAQ 8\/8/);assert.match(done,/卖点 5\/5/);
});
