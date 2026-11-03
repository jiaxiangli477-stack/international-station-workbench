const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function screen(product={id:'p',title:'Example',revision:1,facts:{store:'store'}}){
 const callbacks={},calls=[],drawers=[];
 const c={console,Set,Map,URLSearchParams,location:{hash:'#workproduct?item=p'},document:{addEventListener:(kind,fn,capture)=>(callbacks[kind]??=[]).push({fn,capture})},esc:x=>String(x??''),head:()=>'',teamViewOnly:()=>false,safeReference:x=>x,executionURL:id=>'#workproduct?item='+id,executionData:{products:[product],jobs:[],stores:[]},workproductPage:()=>'',modulePage:()=>'',selectionPage:()=>'',hubPreviewProducts(){},openDrawer:x=>drawers.push(x),closeDrawer(){},render(){},toast(){}};
 c.executionCommand=async data=>{calls.push(data);return data.action==='workflow.preview'?{eligible:1,items:[{id:'p',revision:1,title:'Example',eligible:true,message:'ready'}]}:{started:['p']}};
 vm.createContext(c);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../production_ui.js'),'utf8'),c);
 async function clickAction(action,extra={}){await callbacks.click.find(x=>x.capture).fn({target:{closest:()=>({dataset:{action,id:'p',...extra}})},preventDefault(){},stopImmediatePropagation(){}})}
 async function click(target){await clickAction('flow-preview',{target})}
 return {c,calls,drawers,click,clickAction,product};
}
test('images offers explicit VISUALS and listing offers explicit DRAFT on the same product',()=>{
 const s=screen();
 assert.match(s.c.productionWorkspace('images'),/data-action="flow-preview"[^>]*data-target="VISUALS"/);
 assert.match(s.c.productionWorkspace('listing'),/data-action="flow-preview"[^>]*data-target="DRAFT"/);
 assert.match(s.c.productionPanel(s.product),/data-action="flow-preview"[^>]*data-target="DRAFT"/);
});
test('explicit target reaches workflow preview and keeps the existing hero policy',async()=>{
 const p={id:'p',title:'Example',revision:1,facts:{store:'store'},workflow:{target:'VISUALS',status:'VISUALS_READY',approvalPolicy:'single-hero-v1'}};
 const s=screen(p); await s.click('DRAFT');
 assert.equal(s.calls[0].target,'DRAFT'); assert.equal(s.calls[0].approvalPolicy,'single-hero-v1');
 const visual=screen(); await visual.click('VISUALS'); assert.equal(visual.calls[0].target,'VISUALS');
 assert.match(visual.drawers[0],/仅图片完成|图片完成后停止/);
 assert.doesNotMatch(visual.drawers[0],/自动制作完整套图、质检和保存后台草稿/);
});
test('VISUALS hero confirmation describes only-image scope',async()=>{
 const p={id:'p',title:'Example',revision:1,facts:{store:'store'},workflow:{target:'VISUALS',approvalPolicy:'single-hero-v1',status:'WAITING_HERO_REVIEW'},attributePlan:{fingerprint:'fp'},hero:{revision:1,job:'h',templateVerified:true,pixelHash:'hash',attributePlanFingerprint:'fp',images:[{slot:'m1',file:'m1.png'}]}};
 const s=screen(p);const html=s.c.productionPanel(p,'VISUALS');
 assert.doesNotMatch(html,/自动完成套图、机器质检和草稿保存/);
});
test('existing draft clues disable new draft creation in listing and product controls',()=>{
 for(const clue of [{draft:{draft_id:'123',fields:{}}},{draftHistory:[{draft_id:'123'}]}]){
  const s=screen({id:'p',title:'Example',revision:1,facts:{store:'store'},...clue});
  assert.match(s.c.productionWorkspace('listing'),/data-action="flow-preview"[^>]*data-target="DRAFT"[^>]*disabled/);
 }
});
test('failed current native hero exposes cached-task resume and blocks a new preview',async()=>{
 const s=screen({id:'p',title:'Example',revision:2,facts:{store:'store'},workflow:{approvalPolicy:'single-hero-v1',status:'NEEDS_ATTENTION'}});
 s.c.executionData.jobs=[{id:'hero-failed',product:'p',revision:2,kind:'hero',imageProvider:'codex-native',status:'NEEDS_ATTENTION',updated:'2026-10-22T10:00:00Z'}];
 const html=s.c.productionPanel(s.product);
 assert.match(html,/data-action="flow-native"[^>]*data-job="hero-failed"/);
 assert.match(html,/data-action="flow-preview"[^>]*disabled/);
 await s.click('DRAFT');assert.equal(s.calls.length,0);
 vm.runInContext("productionBatch={items:[{id:'p',revision:2}],target:'DRAFT',approvalPolicy:'single-hero-v1'}",s.c);
 await s.clickAction('flow-start');assert.equal(s.calls.length,0);
 s.c.executionData.jobs[0].executorStillRunning=true;
 assert.match(s.c.productionPanel(s.product),/data-action="flow-native"[^>]*disabled/);
});
test('resume selection validates explicit pointer and excludes unrelated jobs',()=>{
 const s=screen({id:'p',title:'Example',revision:2,facts:{store:'store'},workflow:{resumeJob:'wrong'}});
 const base={product:'p',revision:2,kind:'hero',imageProvider:'codex-native',status:'NEEDS_ATTENTION'};
 for(const change of [{revision:1},{imageProvider:'configured'},{kind:'listing'},{product:'other'},{status:'SUCCESS'}]){
  s.c.executionData.jobs=[{...base,id:'wrong',...change}];
  assert.doesNotMatch(s.c.productionPanel(s.product),/data-action="flow-native"/);
 }
 s.c.executionData.jobs=[{...base,id:'old',updated:'2026-10-22T08:00:00Z'},{...base,id:'new',kind:'visual',updated:'2026-10-22T09:00:00Z'}];
 assert.match(s.c.productionPanel(s.product),/data-action="flow-native"[^>]*data-job="new"/);
 s.product.workflow.resumeJob='old';
 assert.match(s.c.productionPanel(s.product),/data-action="flow-native"[^>]*data-job="old"/);
});

test('a newer verified current suite does not offer an obsolete failed task for resume',async()=>{
 const s=screen({id:'p',title:'Example',revision:2,facts:{store:'store'},attributePlan:{fingerprint:'current'},visual:{job:'complete',revision:2,attributePlanFingerprint:'current',templateCount:18,images:[]},workflow:{approvalPolicy:'single-hero-v1',status:'NEEDS_INPUT'}});
 s.c.executionData.jobs=[
  {id:'partial',product:'p',revision:2,kind:'visual',imageProvider:'codex-native',status:'NEEDS_ATTENTION',created:'2026-10-25T10:00:00Z'},
  {id:'complete',product:'p',revision:2,kind:'visual',status:'SUCCESS',created:'2026-10-26T10:00:00Z'}];
 assert.equal(s.c.productionResumeJob(s.product),null);
 assert.doesNotMatch(s.c.productionPanel(s.product),/data-action="flow-native"/);
 await s.click('DRAFT');assert.equal(s.calls[0].action,'workflow.preview');
 s.product.visual.attributePlanFingerprint='old';
 assert.equal(s.c.productionResumeJob(s.product).id,'partial','changed binding still needs review');
});

test('original Skill preparation uses its own action and keeps the current product expanded',async()=>{
 const s=screen({id:'p',title:'Example',revision:5,facts:{store:'store'}});let reopened=false;
 s.c.document.querySelectorAll=()=>[{dataset:{id:'p'},closest:()=>({setAttribute:(key)=>{reopened=key==='open';}})}];
 await s.clickAction('flow-skill-prepare');
 assert.equal(s.calls[0].action,'listing.skill.prepare');assert.equal(s.calls[0].revision,5);
 assert.equal(s.calls.some(call=>call.action==='listing.bridge.prepare'),false);
 assert.equal(reopened,true);
});

test('listing preview reuses local images without introducing an independent CDN bridge prerequisite',()=>{
 const s=screen({id:'p',title:'Example',revision:5,facts:{store:'store'},visual:{revision:5,job:'images',templateCount:18,images:[]}});
 const html=s.c.productionPanel(s.product);
 assert.match(html,/data-action="flow-skill-prepare"/);assert.match(html,/原Skill上品预检/);
 assert.match(html,/原上传脚本使用本地图片/);
 assert.doesNotMatch(html,/桥接整理上品素材|flow-bridge-prepare|listingBridge|CDN.*(?:待补|前置)|不要求浏览器登录/);
 assert.doesNotMatch(s.c.productionPanel(s.product,'VISUALS'),/data-action="flow-skill-prepare"/);
});

test('current original-Skill preflight result is visible without being reported as a saved draft',()=>{
 const s=screen({id:'p',title:'Example',revision:5,facts:{store:'store'},listingBridge:{revision:5,message:'OBSOLETE CDN PENDING'},listingSkill:{revision:5,status:'READY',message:'原Skill方案预检完成',images:18,content_preflight:{status:'PASS'},field_replacements:[{key:'form',from:'gel',to:'powder',requirement:'剂型匹配',status:'DESIGN'}],pending_requirements:['类目待核验'],draftSaved:false}});
 const html=s.c.productionPanel(s.product);
 assert.match(html,/原Skill方案预检完成/);assert.match(html,/内容预检：通过/);assert.match(html,/字段替换/);assert.match(html,/form：powder/);assert.match(html,/剂型匹配/);assert.match(html,/类目待核验/);
 assert.doesNotMatch(html,/OBSOLETE CDN PENDING|已完成实际回读|草稿已保存并回读/);
 s.product.listingSkill.revision=4;assert.doesNotMatch(s.c.productionPanel(s.product),/原Skill方案预检完成/);
});

test('unknown original-Skill preflight status stays incomplete and preserves design provenance',()=>{
 const s=screen({id:'p',title:'Example',revision:5,facts:{store:'store'},listingSkill:{revision:5,status:'NEW_ENUM',content_preflight:{status:'UNKNOWN'},field_replacements:[{key:'form',to:'powder',status:'DESIGN'}],draftSaved:false}});
 const before=JSON.stringify(s.product),html=s.c.productionListingSkillResult(s.product);
 assert.match(html,/预检未完成/);assert.doesNotMatch(html,/预检完成|草稿已保存|已完成实际回读/);assert.equal(JSON.stringify(s.product),before);
});

test('listing browser button opens only the connection action and respects view-only mode',async()=>{
 const s=screen({id:'p',title:'Example',revision:6,facts:{store:'store'}});
 assert.match(s.c.productionPanel(s.product),/打开上品浏览器/);
 await s.clickAction('flow-listing-browser');
 assert.equal(s.calls.length,1);assert.equal(s.calls[0].action,'listing.browser.open');assert.equal(s.calls[0].revision,6);
 assert.match(s.drawers[0],/原Skill上品浏览器/);
 s.c.teamViewOnly=()=>true;
 assert.match(s.c.productionPanel(s.product),/data-action="flow-listing-browser"[^>]*disabled/);
});
