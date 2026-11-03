const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function screen(viewer=false){
 const p={id:'p',revision:6,facts:{store:'youhealth'},recruitment:{topicId:'133',store:'youhealth'},
  draft:{draft_id:'123',revision:6,store:'youhealth',readback_verified:true},
  rectification:{rows:[],blockers:[],store:'youhealth',topicId:'133',businessType:'HOT_PRODUCT',fingerprint:'a'.repeat(64),
   matchedCount:0,manualCount:0,platform:{status:'FAILED',checkedAt:'now',items:[{itemName:'图片检测',itemValue:['主体相似'],meet:false,score:.22}]}}};
 const callbacks={},calls=[];
 const s={workproductPage:()=>'',executionProduct:()=>p,executionData:{products:[p]},console,
  document:{addEventListener:(name,fn)=>(callbacks[name]??=[]).push(fn)},teamViewOnly:()=>viewer,
  esc:x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  safeReference:()=>'',integrationDate:x=>x,render:()=>{},toast:()=>{},
  executionCommand:async payload=>{calls.push(payload);return p}};
 vm.createContext(s);vm.runInContext(fs.readFileSync(path.join(__dirname,'../rectification_ui.js'),'utf8'),s);
 return {s,p,calls,click:async()=>{const button={dataset:{action:'rectification-detect',id:'p'},disabled:false};
  for(const fn of callbacks.click)await fn({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}})}};
}
test('a verified saved draft can run the actual platform check and display a failed qualification',()=>{
 const {s,p}=screen(),html=s.rectificationPanel(p);
 assert.match(html,/data-action="rectification-detect"/);assert.doesNotMatch(html,/data-action="rectification-detect"[^>]*disabled/);
 assert.match(html,/已检测.*未符合/);assert.match(html,/图片检测/);assert.match(html,/不报名或发布/);
});
test('the platform check button calls only the readonly detection action for the current revision',async()=>{
 const t=screen();await t.click();assert.equal(t.calls.length,1);assert.equal(t.calls[0].action,'recruitment.detect');
 assert.equal(t.calls[0].id,'p');assert.equal(t.calls[0].revision,6);
});
test('foreign or stale drafts and viewers cannot run checks, and platform text remains escaped',async()=>{
 const {s,p}=screen();p.draft.revision=5;assert.match(s.rectificationPanel(p),/data-action="rectification-detect"[^>]*disabled/);
 p.draft.revision=6;p.rectification.platform.items[0].itemName='<img src=x onerror=alert(1)>';
 const html=s.rectificationPanel(p);assert.doesNotMatch(html,/<img src=x/);assert.match(html,/&lt;img/);
 const viewer=screen(true);await viewer.click();assert.equal(viewer.calls.length,0);
});
