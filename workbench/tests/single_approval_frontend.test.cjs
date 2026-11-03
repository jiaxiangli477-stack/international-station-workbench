const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function screen(product={id:'p',revision:1,title:'Test',facts:{store:'store'}}){
 const listeners={},out={calls:[],drawers:[],toasts:[],renders:0};
 const c={console,URLSearchParams,Set,Map,document:{addEventListener:(kind,fn,capture)=>(listeners[kind]??=[]).push({fn,capture})},location:{hash:'#workproduct?item=p'},teamViewOnly:()=>false,executionData:{products:[product],jobs:[],stores:[]},esc:x=>String(x??''),safeReference:x=>x,head:()=>'',workproductPage:()=>'',modulePage:()=>'',selectionPage:()=>'',hubPreviewProducts(){},openDrawer:html=>out.drawers.push(html),closeDrawer(){},toast:x=>out.toasts.push(x),render:()=>out.renders++,executionURL:id=>'#workproduct?item='+id,topicStore:'store',recruitType:'1',recruitLoading:false,recruitImageSelected:new Set(['t']),selectedCandidates:new Set(['c']),FormData:class{constructor(form){this.form=form}*[Symbol.iterator](){yield* Object.entries(this.form.values||{})}}};
 c.executionCommand=async data=>{out.calls.push(data);if(data.action==='workflow.adopt')return {items:[{id:'p',revision:1}]};if(data.action==='workflow.preview')return {eligible:1,items:[{id:'p',revision:1,eligible:true,title:'Test',message:'首图准备'}]};if(data.action==='workflow.start')return {started:['p']};return product};
 vm.createContext(c);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../production_ui.js'),'utf8'),c);
 async function click(action,extra={}){const event={target:{closest:()=>({dataset:{action,id:'p',...extra}})},preventDefault(){},stopImmediatePropagation(){}};await listeners.click.find(x=>x.capture).fn(event)}
 async function submit(form){await listeners.submit.find(x=>x.capture).fn({target:form,preventDefault(){},stopImmediatePropagation(){}})}
 return {c,out,click,submit,product};
}
const heroProduct=()=>({id:'p',revision:2,title:'Test',facts:{store:'store'},attributePlan:{fingerprint:'fp'},workflow:{approvalPolicy:'single-hero-v1',status:'WAITING_HERO_REVIEW'},hero:{job:'hero-job',revision:2,attributePlanFingerprint:'fp',pixelHash:'pixels',templateVerified:true,images:[{slot:'m1',file:'m1.png'}]}});
test('new direct and adopted entrypoints explicitly enable one hero policy and DRAFT target',async()=>{
 for(const action of ['flow-preview','selection-batch-preview','recruit-image-preview','recruit-image-one']){
  const s=screen();vm.runInContext("productionStore='store'",s.c);await s.click(action);
  const preview=s.out.calls.find(x=>x.action==='workflow.preview');assert.equal(preview.approvalPolicy,'single-hero-v1');assert.equal(preview.target,'DRAFT');
  await s.click('flow-start');assert.equal(s.out.calls.at(-1).approvalPolicy,'single-hero-v1');assert.equal(s.out.calls.at(-1).target,'DRAFT');
 }
});
test('legacy existing workflow is not silently upgraded',async()=>{
 const s=screen({id:'p',revision:1,title:'Legacy',facts:{store:'store'},workflow:{status:'WAITING_PACKAGING_REVIEW',target:'DRAFT'}});
 await s.click('flow-preview');assert.notEqual(s.out.calls[0].approvalPolicy,'single-hero-v1');
});
test('hero review shows actual m1 then sends the bound dedicated approval only after acknowledgement',async()=>{
 const s=screen(heroProduct()),html=s.c.productionPanel(s.product);assert.match(html,/首图待确认/);assert.doesNotMatch(html,/审核当前包装|审核当前套图/);
 await s.click('flow-hero-review');const drawer=s.out.drawers.at(-1);assert.match(drawer,/task-assets\/hero-job\/m1.png/);assert.match(drawer,/确认首图并自动制作到草稿/);
 const form={id:'productionHeroReview',dataset:{id:'p',revision:'2',job:'hero-job',fingerprint:'fp',pixelHash:'pixels'},values:{}};
 await s.submit(form);assert.equal(s.out.calls.length,0);
 form.values.acknowledgeHero='on';await s.submit(form);assert.deepEqual(JSON.parse(JSON.stringify(s.out.calls[0])),{action:'hero.approve',id:'p',revision:2,artifactJob:'hero-job',fingerprint:'fp',pixelHash:'pixels',acknowledgeHero:true});
});
test('stale or unverified hero cannot be presented as a confirmable current m1',async()=>{
 const p=heroProduct();p.hero.attributePlanFingerprint='old';const s=screen(p);await s.click('flow-hero-review');assert.equal(s.out.drawers.length,0);assert.match(s.out.toasts[0],/变化|核验/);
});
test('new policy keeps unknown facts and failed quality visible without repeat human gates',()=>{
 const p=heroProduct();p.workflow={approvalPolicy:'single-hero-v1',status:'NEEDS_ATTENTION',gaps:['真实MOQ未知'],message:'机器质检失败'};p.workflowPlan={gaps:['规格未通过']};p.packaging={revision:2,job:'A0',images:[]};p.visual={revision:2,job:'v',images:[]};const s=screen(p),html=s.c.productionPanel(p);
 assert.match(html,/真实MOQ未知/);assert.match(html,/规格未通过/);assert.match(html,/机器质检失败/);assert.doesNotMatch(html,/审核当前包装|审核当前套图|确认包装设计稿/);
});
test('draft receipt invites final backend check and refresh never marks publication locally',async()=>{
 const p={id:'p',revision:1,title:'Test',facts:{store:'store'},draft:{draft_id:'d',draft_url:'https://example.com/d',readback_verified:true,fields:{}}};const s=screen(p),html=s.c.productionReceipt(p);
 assert.match(html,/草稿待用户检查/);assert.match(html,/自行.*发布/);assert.match(html,/刷新发布状态/);assert.doesNotMatch(html,/>已发布</);
 await s.click('flow-publication-refresh');assert.deepEqual(JSON.parse(JSON.stringify(s.out.calls[0])),{action:'publication.refresh',id:'p',recoverBrowser:true});assert.equal(p.publication,undefined);
});
test('published label requires authoritative matching platform evidence',()=>{
 const p={id:'p',revision:1,facts:{store:'store'},draft:{product_id:'123',draft_id:'d',fields:{}},publication:{status:'published',published:true,store:'store',draft_id:'d',product_id:'123',checked_at:'2026-10-22',authority:{identity_verified:true,method:'GET',source_url:'https://example.com/product/123'}}};
 const s=screen(p);assert.match(s.c.productionPublication(p),/>已发布</);
 for(const change of [{store:'other'},{draft_id:'other'},{product_id:'999'},{published:null},{authority:{identity_verified:false}}])assert.doesNotMatch(s.c.productionPublication({...p,publication:{...p.publication,...change}}),/>已发布</);
 assert.match(s.c.productionPublication({...p,draft:{draft_id:'d'},publication:{...p.publication,product_id:'d'}}),/>已发布</);
});
test('read-only view cannot approve hero or refresh authenticated platform state',async()=>{
 const s=screen(heroProduct());s.c.teamViewOnly=()=>true;assert.match(s.c.productionPanel(s.product),/data-action="flow-hero-review"[^>]*disabled/);
 await s.click('flow-hero-review');await s.click('flow-publication-refresh');assert.equal(s.out.calls.length,0);
});
