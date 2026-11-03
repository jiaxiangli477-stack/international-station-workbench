const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../cloud_team_ui.js'),'utf8');
async function fixture(viewer=false){
 const actions=[],previews=[],listeners={};let fetches=0;
 const scope={tasksPage:()=>'<main>BASE</main>',teamViewOnly:()=>viewer,current:'tasks',render:()=>{},toast:()=>{},setInterval:()=>{},
  esc:s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),executionURL:id=>'#workproduct?item='+id,
  document:{body:{classList:{contains:()=>false}},addEventListener:(type,fn)=>listeners[type]=fn},
  fetch:async()=>{fetches++;return {ok:true,json:async()=>({requests:[{id:'request-id',store:'youhealth',taskType:'images',selected:['candidate-1'],note:'<script>untrusted</script>',createdAt:'2026-10-27',status:'RECEIVED_LOCAL'}],health:{status:'SUCCESS',updatedAt:'now'}})}},
  executionCommand:async payload=>{actions.push(payload);return {items:[{id:'P-fixture',revision:1}],store:'youhealth',taskType:'images'}},
  productionPreview:async(items,store)=>previews.push({items,store})};
 vm.createContext(scope);vm.runInContext(source,scope);await new Promise(r=>setImmediate(r));
 return {scope,actions,previews,listeners,fetches:()=>fetches};
}
test('owner sees escaped external notes and a review action',async()=>{
 const f=await fixture();const html=f.scope.tasksPage();assert.ok(html.includes('外部团队任务申请'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>untrusted'));assert.ok(html.includes('cloud-adopt'));
});
test('viewer never loads or displays the administrator request inbox',async()=>{
 const f=await fixture(true);assert.equal(f.scope.tasksPage(),'<main>BASE</main>');assert.equal(f.fetches(),0);
});
test('accepting a request opens original preflight without starting a paid workflow',async()=>{
 const f=await fixture();const button={dataset:{action:'cloud-adopt',id:'request-id'},disabled:false};
 await f.listeners.click({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}});
 assert.equal(f.actions.length,1);assert.equal(f.actions[0].action,'cloud.adopt');assert.equal(f.previews.length,1);
 assert.ok(!f.actions.some(x=>x.action==='workflow.start'));
});
test('a failed inbox reload shows the connection error and leaves sync retry enabled',async()=>{
 const f=await fixture();let renders=0;f.scope.render=()=>renders++;
 f.scope.fetch=async()=>{throw Error('offline')};
 const button={dataset:{action:'cloud-sync'},disabled:false};
 await f.listeners.click({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}});
 assert.equal(button.disabled,false);assert.equal(renders,1);
 assert.ok(f.scope.tasksPage().includes('云端申请暂未连接'));
});
