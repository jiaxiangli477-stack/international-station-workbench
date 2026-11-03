const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const base=path.resolve(__dirname,'..');
function env(){
 const handlers={},out={calls:[],toasts:[],drawers:[],renders:0};
 const els={productionManifest:{value:JSON.stringify({fields:{product_name:'Changed'}})},productionUnresolved:{value:''},productionPlanAcknowledged:{checked:false}};
 let modal=false;
 const c={console,URL,URLSearchParams,Set,Map,FormData:class{constructor(form){this.form=form} *[Symbol.iterator](){yield* Object.entries(this.form.values||{})}},
 document:{addEventListener:(type,fn,capture)=>{(handlers[type]??=[]).push({fn,capture})},activeElement:{tagName:'BODY'},body:{classList:{contains:()=>modal}},getElementById:id=>els[id]||null,querySelector:()=>null,querySelectorAll:()=>[]},
 window:{addEventListener(){}},location:{hash:'#workproduct?item=p'},current:'workproduct',teamViewOnly:()=>false,
 render:()=>out.renders++,esc:x=>String(x??''),head:()=>'',workproductPage:()=>'',modulePage:()=>'',selectionPage:()=>'',demandsPage:()=>'',hubPreviewProducts:()=>{},executionURL:id=>'#workproduct?item='+id,
 openDrawer:html=>out.drawers.push(html),closeDrawer(){},toast:s=>out.toasts.push(s),setInterval(){},clearInterval(){}};
 vm.createContext(c);
 const load=file=>vm.runInContext(fs.readFileSync(path.join(base,file),'utf8'),c);
 const submit=async form=>{const e={target:form,submitter:{value:'approve'},preventDefault(){},stopImmediatePropagation(){}};await handlers.submit.find(h=>h.capture).fn(e)};
 const click=async(action,id='p',extra={})=>{const el={dataset:{action,id,...extra},disabled:false};let stopped=false;const e={target:{closest:()=>el},preventDefault(){},stopImmediatePropagation(){stopped=true}};for(const h of handlers.click.filter(h=>h.capture)){await h.fn(e);if(stopped)return}for(const h of handlers.click.filter(h=>!h.capture))await h.fn(e)};
 return {c,out,handlers,els,load,submit,click,modal:value=>modal=value};
}
test('deferred polling renders latest status after blur or modal close, without overwriting editing',async()=>{
 for(const protection of ['focus','modal','dirty']){
  const s=env();s.load('execution_ui.js');let response={products:[],jobs:[{id:'j',status:'RUNNING'}]};s.c.fetch=async()=>({ok:true,json:async()=>structuredClone(response)});
  await s.c.refreshExecution();const initial=s.out.renders;
  if(protection==='focus')s.c.document.activeElement={tagName:'INPUT'};if(protection==='modal')s.modal(true);if(protection==='dirty')vm.runInContext('executionDirty=true',s.c);
  response.jobs[0].status='SUCCESS';await s.c.refreshExecution();assert.equal(s.out.renders,initial);
  response.jobs[0].status='NEEDS_ATTENTION';await s.c.refreshExecution();assert.equal(s.out.renders,initial);
  s.c.document.activeElement={tagName:'BODY'};s.modal(false);vm.runInContext('executionDirty=false',s.c);
  await s.c.refreshExecution();assert.equal(s.out.renders,initial+1);await s.c.refreshExecution();assert.equal(s.out.renders,initial+1);
  assert.equal(vm.runInContext('executionData.jobs[0].status',s.c),'NEEDS_ATTENTION');
 }
});
function attributeEnv(failApproval=false){
 const s=env(),p={id:'p',revision:1,attributePlan:{job:'a',fingerprint:'old',manifest:{fields:{product_name:'Original'}},field_sources:{}}};s.c.executionData={products:[p],jobs:[]};let fingerprint='old',failed=false;
 s.c.executionCommand=async data=>{s.out.calls.push(data);if(data.action==='attributes.edit'){assert.equal(data.fingerprint,fingerprint);fingerprint+='x';p.attributePlan={...p.attributePlan,fingerprint,manifest:data.manifest};return structuredClone(p)}if(failApproval&&!failed){failed=true;throw Error('approval temporarily failed')}assert.equal(data.fingerprint,fingerprint);return p};
 s.load('production_ui.js');const form={id:'productionAttributeForm',dataset:{id:'p',fingerprint:'old',revision:'1'},querySelectorAll:()=>[{dataset:{planField:'product_name',valueType:'string'},value:'Changed'}]};return {...s,p,form};
}
test('unchecked attribute approval sends no writes and checking permits direct retry',async()=>{
 const s=attributeEnv();await s.submit(s.form);assert.equal(s.out.calls.length,0);assert.match(s.out.toasts[0],/勾选/);
 s.els.productionPlanAcknowledged.checked=true;await s.submit(s.form);assert.deepEqual(s.out.calls.map(c=>c.action),['attributes.edit','attributes.approve']);
});
test('edit success and approval failure updates form fingerprint for direct retry',async()=>{
 const s=attributeEnv(true);s.els.productionPlanAcknowledged.checked=true;await s.submit(s.form);assert.equal(s.form.dataset.fingerprint,'oldx');
 await s.submit(s.form);assert.deepEqual(s.out.calls.map(c=>c.action),['attributes.edit','attributes.approve','attributes.edit','attributes.approve']);assert.equal(s.out.calls[2].fingerprint,'oldx');
});
test('single recruitment preview uses workflow attribute-first contract and new approved DRAFT policy',async()=>{
 const s=env();Object.assign(s.c,{topicStore:'store',recruitType:'1',recruitLoading:false,nativeTypes:{'1':'主题'},recruitHubTab:'topics',hubWriteRoute(){},executionData:{products:[],jobs:[]}});
 s.c.executionCommand=async data=>{s.out.calls.push(data);if(data.action==='workflow.adopt')return {items:[{id:'p',revision:1}]};if(data.action==='workflow.preview')return {items:[{id:'p',revision:1,title:'Test',eligible:true,next:'attributes',message:'先准备同源属性'}],eligible:1,target:'VISUALS'};if(data.action==='workflow.start')return {started:['p'],blocked:[]};if(data.action==='topic.images.preview')return {store:'store',businessType:'1',items:[{topic:'t',title:'Test',kind:'packaging',eligible:true,gaps:[]}],eligible:1};if(data.action==='topic.images.start')return {started:['p'],blocked:[]};throw Error(data.action)};
 s.load('recruitment_images.js');s.load('production_ui.js');await s.click('recruit-image-one','t');
 assert.deepEqual(s.out.calls.map(c=>c.action),['workflow.adopt','workflow.preview']);assert.equal(s.out.calls[1].target,'DRAFT');assert.equal(s.out.calls[1].approvalPolicy,'single-hero-v1');assert.match(s.out.drawers.at(-1),/首图m1/);
 await s.click('flow-start');assert.equal(s.out.calls.at(-1).action,'workflow.start');assert.equal(s.out.calls.at(-1).target,'DRAFT');assert.equal(s.out.calls.at(-1).acknowledgeExecution,true);
});
test('unchecked specification status is visible and visual approval requires an explicit checkbox',async()=>{
 const s=env(),p={id:'p',title:'Test',revision:1,facts:{},visual:{revision:1,job:'v',images:[{slot:'m1',file:'m1.png',specCheck:'unchecked',reviewRequirements:['specification']}],quality:{reviewRequired:true}}};s.c.executionData={products:[p],jobs:[]};s.c.executionCommand=async data=>{s.out.calls.push(data);return p};s.load('production_ui.js');
 assert.match(s.c.productionPanel(p),/待人工规格核对/);assert.match(s.c.productionPanel({...p,visual:{revision:1,job:'old',images:[{slot:'m1',file:'m1.png'}]}}),/待人工规格核对/);
 await s.click('execution-approve','p',{phase:'visual'});assert.match(s.out.drawers.at(-1),/name="specificationReviewed"[^>]*type="checkbox"[^>]*required/);
 const form={id:'productionArtifactReview',dataset:{id:'p',phase:'visual',revision:'1',job:'v'},values:{}};await s.submit(form);assert.equal(s.out.calls.length,0);
 form.values.specificationReviewed='on';await s.submit(form);assert.equal(s.out.calls[0].specificationReviewed,true);
});
test('current verified spec receipts retain their status and row-level review flags stay pending',()=>{
 const s=env();s.c.executionData={products:[],jobs:[]};s.load('production_ui.js');
 const p={revision:1,visual:{revision:1,job:'v',images:[{slot:'m1',file:'m1.png',specCheck:'ok'},{slot:'m2',file:'m2.png',specCheck:'not_applicable'},{slot:'m3',file:'m3.png',specCheck:'ok',quality:{reviewRequired:true}}]}};
 const rows=s.c.productionOutputs(p);assert.equal(rows.get('m1').state,'套图已核验');assert.equal(rows.get('m2').state,'套图已核验');assert.match(rows.get('m3').state,/待人工规格核对/);
});
test('legacy approval entry also requires explicit specification acknowledgement',async()=>{
 const s=env();s.load('execution_ui.js');vm.runInContext("executionData={products:[{id:'p',title:'Test',revision:1}],jobs:[]}",s.c);s.c.executionCommand=async data=>{s.out.calls.push(data);return {}};
 await s.click('execution-approve','p',{phase:'visual'});assert.match(s.out.drawers.at(-1),/name="specificationReviewed"/);
 const form={id:'productionApproval',dataset:{id:'p',phase:'visual',revision:'1'},values:{}};
 await s.handlers.submit[0].fn({target:form,preventDefault(){}});assert.equal(s.out.calls.length,0);
 form.values.specificationReviewed='on';await s.handlers.submit[0].fn({target:form,preventDefault(){}});assert.equal(s.out.calls[0].specificationReviewed,true);
});
test('images-only workflow keeps its target when resuming native output and labels its completion',async()=>{
 const s=env(),p={id:'p',revision:1,facts:{store:'store'},workflow:{target:'VISUALS',status:'VISUALS_READY'}};
 s.c.executionData={products:[p],jobs:[]};s.c.executionCommand=async data=>{s.out.calls.push(data);return {}};s.load('production_ui.js');
 assert.match(s.c.productionPanel(p),/仅图片制作与审核完成/);assert.doesNotMatch(s.c.productionPanel(p),/一键生图并保存草稿|终点为后台草稿/);
 await s.click('flow-native-confirm','p',{job:'v'});assert.equal(s.out.calls[1].target,'VISUALS');
});
