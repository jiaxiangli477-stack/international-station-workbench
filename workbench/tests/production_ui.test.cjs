const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function screen(viewer=false){
 const context={console,Set,URLSearchParams,listeners:{},document:{addEventListener(name,handler){context.listeners[name]=handler},getElementById(){return null}},
  teamViewOnly:()=>viewer,esc:x=>String(x??''),head:()=>'',executionData:{products:[],jobs:[],stores:[]},
  workproductPage:()=>'',modulePage:()=>'',selectionPage:()=>'',hubPreviewProducts:()=>{},
  executionURL:id=>'#workproduct?item='+id,location:{hash:''}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('production_ui.js','utf8'),context);return context;
}
const fixture={id:'p',title:'New powder',source:'selection:c',revision:1,facts:{mode:'concept'},
 workflowPlan:{next:'attributes_review',gaps:['新品属性方案审核']},
 visualPartial:{revision:1,job:'images',images:[{slot:'m3',file:'m3.png'}]},
 visualPending:{revision:1,job:'images',images:[{slot:'m1',file:'m1.png'}]}};
test('partial and pending outputs share the same 19-slot gallery',()=>{
 const s=screen(),html=s.productionPanel(fixture);
 assert.match(html,/m3/);assert.match(html,/m1/);assert.match(html,/待核验/);
 assert.match(html,/2\/19/);assert.match(html,/新品属性方案审核/);
 assert.match(html,/一键生图并保存草稿/);
});
test('read-only viewers get explanation and cannot start a production task',()=>{
 const s=screen(true),html=s.productionPanel(fixture);
 assert.match(html,/只读/);
 assert.match(html,/data-action="flow-preview"[^>]*disabled/);
});
test('manual and selected references are sources, not additional visual modes',()=>{
 const s=screen();
 assert.equal(s.productionSource({...fixture,source:'manual:x'}),'新品需求');
 assert.equal(s.productionSource(fixture),'选品参考');
 assert.equal(s.productionSource({...fixture,recruitment:{topicId:'1'}}),'征品参考');
});

test('original Skill draft separates verified fields from images awaiting final review',()=>{
 const s=screen(),product={...fixture,draft:{draft_id:'draft-fixture',readback_verified:true,image_readback_verified:false,image_review_required:true,fields:{title:{expected:'Powder',actual:'Powder',matched:true}}}};
 const before=JSON.stringify(product),html=s.productionReceipt(product);
 assert.match(html,/草稿已保存，原Skill字段回读通过；图片分区\/顺序待后台终检/);
 assert.doesNotMatch(html,/已完成实际回读|图片已核验|图片分区已通过/);
 assert.equal(JSON.stringify(product),before);
 product.draft.readback_verified=false;
 assert.doesNotMatch(s.productionReceipt(product),/字段回读通过/);
 assert.match(s.productionReceipt(product),/保存或回读结果待核对/);
});

test('original Skill preparation only displays for the same plan and visual job',()=>{
 const s=screen(),p={revision:1,attributePlan:{fingerprint:'a'},visual:{job:'v'},
  listingSkill:{revision:1,attributePlanFingerprint:'a',visualJob:'v',status:'BLOCKED',message:'current result'}};
 assert.match(s.productionListingSkillResult(p),/current result/);
 p.listingSkill.visualJob='old';assert.equal(s.productionListingSkillResult(p),'');
 p.listingSkill.visualJob='v';p.listingSkill.attributePlanFingerprint='old';assert.equal(s.productionListingSkillResult(p),'');
});
test('existing-draft recovery includes its product identity and requests only saved-draft readback',async()=>{
 const s=screen(),p={...fixture,draft:{draft_id:'123'}};
 s.executionData.products=[p];s.executionData.jobs=[{id:'j',product:p.id,status:'NEEDS_ATTENTION',recoveryRequired:true}];
 const html=s.productionPanel(p);
 assert.match(html,/data-action="flow-reconcile"[^>]*data-id="p"/);
 const payloads=[];s.executionCommand=async payload=>payloads.push(payload);s.render=()=>{};s.toast=()=>{};
 const button={dataset:{action:'flow-reconcile',id:p.id,job:'j'}};
 await s.listeners.click({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}});
 assert.equal(payloads.length,1);assert.equal(payloads[0].action,'job.reconcile-output');
 assert.equal(payloads[0].id,'j');assert.equal(payloads[0].refreshSavedDraft,true);
});
test('a verified same-scope saved draft supersedes old pending-save preflight wording',()=>{
 const s=screen(),p={id:'p',revision:6,facts:{store:'store'},attributePlan:{fingerprint:'fp'},visual:{job:'v'},
  listingSkill:{revision:6,attributePlanFingerprint:'fp',visualJob:'v',status:'READY',allowMissingNetWeight:true,
    message:'后台是否允许保存尚待实际校验',images:18},
  draft:{revision:6,store:'store',readback_verified:true}};
 assert.match(s.productionListingSkillResult(p),/草稿已保存并回读/);
 assert.doesNotMatch(s.productionListingSkillResult(p),/尚待实际校验/);
 p.draft.revision=5;assert.match(s.productionListingSkillResult(p),/尚待实际校验/);
});
test('browser connection diagnostics are explicit, readonly, and do not claim shop authentication',async()=>{
 const s=screen();s.executionData.products=[fixture];
 const calls=[];s.executionCommand=async data=>{calls.push(data);return {status:'DISCONNECTED',message:'专用浏览器未连接',accountVerified:false}};
 s.render=()=>{};s.toast=()=>{};
 const button={dataset:{action:'flow-listing-browser-status',id:fixture.id}};
 await s.listeners.click({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}});
 assert.equal(calls.length,1);assert.equal(calls[0].action,'listing.browser.status');
 assert.match(s.productionBrowserNote(),/未连接/);
 assert.match(s.productionPanel(fixture),/data-action="flow-listing-browser-status"[^>]*data-id="p"/);
});
