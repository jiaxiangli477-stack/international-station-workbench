const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('listing_runner.cjs','utf8');
const start=source.indexOf('async function assertIdentity(page)');
const end=source.indexOf("for (const name of ['fillConfiguredField'",start);
assert(start>=0&&end>start);
function setup(originalFlow,observed=['fixture-account'],parameters=0){
 let locatorCalls=0;
 const scope={context:{expectedAccount:'fixture-account'},originalFlow,identity:null};
 vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
 const page={evaluate:async()=>observed,locator:()=>{locatorCalls++;return {count:async()=>parameters}}};
 return {scope,page,locatorCalls:()=>locatorCalls};
}
test('original 18-image flow verifies the real page account without requiring a standalone m7 group',async()=>{
 const s=setup(true);await s.scope.assertIdentity(s.page);
 assert.equal(s.scope.identity.verified,true);assert.equal(s.locatorCalls(),0);
});
test('legacy flow retains its parameter-group requirement after page identity verification',async()=>{
 const missing=setup(false);await assert.rejects(missing.scope.assertIdentity(missing.page),/m7去向/);
 const present=setup(false,['fixture-account'],1);await present.scope.assertIdentity(present.page);
 assert.equal(present.locatorCalls(),1);assert.equal(present.scope.identity.verified,true);
});
test('original and legacy flows both reject an unknown or foreign actual page account',async()=>{
 for(const original of [true,false])for(const observed of [[],['foreign-account']]){
  const s=setup(original,observed,1);await assert.rejects(s.scope.assertIdentity(s.page),/身份尚未核验或与目标店铺不同/);
  assert.equal(s.scope.identity,null);assert.equal(s.locatorCalls(),0);
 }
});
