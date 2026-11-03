const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../listing_runner.cjs'),'utf8');
const start=source.indexOf('async function assertIdentity(page)');
const end=source.indexOf("for (const name of ['fillConfiguredField'",start);
function setup({owner='fixture-account',valueOwner=owner,header=null,host='post.alibaba.com',pathname='/product/publish.htm'}={}){
 const scope={context:{expectedAccount:'fixture-account'},originalFlow:true,identity:null};
 vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
 const window={GPF_GLOBAL_STORE:{json:{models:{global:{adminAliId:owner,value:{adminAliId:valueOwner}}}}},
   __INITIAL_STATE__:{userInfo:{aliId:header}}};
 const page={evaluate:async fn=>vm.runInNewContext('('+fn.toString()+')()',{
   window,location:{hostname:host,pathname},document:{querySelector:()=>null}})};
 return {scope,page};
}
test('current publish-page owner account is accepted even when old header attributes are absent',async()=>{
 const s=setup();await s.scope.assertIdentity(s.page);assert.equal(s.scope.identity.verified,true);
});
test('numeric owner identities from the real publish model compare as strings',async()=>{
 const s=setup({owner:123,valueOwner:123});s.scope.context.expectedAccount='123';
 await s.scope.assertIdentity(s.page);assert.equal(s.scope.identity.verified,true);
});
test('foreign or contradictory current shop owner cannot be overridden by a matching legacy header',async()=>{
 for(const options of [{owner:'foreign',header:'fixture-account'},
   {owner:'fixture-account',valueOwner:'foreign',header:'fixture-account'}]){
   const s=setup(options);await assert.rejects(s.scope.assertIdentity(s.page),/身份尚未核验或与目标店铺不同/);
 }
});
test('unrelated origins and pages never provide publish-page identity proof',async()=>{
 for(const options of [{host:'untrusted.example'},{host:'login.alibaba.com'},{pathname:'/other'}]){
   const s=setup(options);await assert.rejects(s.scope.assertIdentity(s.page),/身份尚未核验或与目标店铺不同/);
 }
});
test('legacy exact account evidence remains available only on the official publish page',async()=>{
 const s=setup({owner:null,valueOwner:null,header:'fixture-account'});
 await s.scope.assertIdentity(s.page);assert.equal(s.scope.identity.verified,true);
});
