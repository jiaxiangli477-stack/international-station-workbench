const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../listing_runner.cjs'),'utf8');
const start=source.indexOf('let identity = null;');
const end=source.indexOf('async function uploadWithEvidence',start);
assert(start>=0&&end>start,'execute write guards must be exercised from the actual runner');
const entrypoints=['dismissFloatingOverlays','fillConfiguredField','fillCustomAttributes',
  'fillCompanyIntroAndFAQ','fillSellingPoints','fillBottleCapacity','fillFlavor',
  'fillLeadTime','clearLogistics','fillLogistics','saveDraft'];

function setup(initialObserved=['fixture-account']) {
  let observed=initialObserved;
  const calls=new Map(),engine={};
  const spy=name=>async(...args)=>{
    calls.set(name,(calls.get(name)||0)+1);
    return {name,args};
  };
  for(const name of entrypoints)engine[name]=spy(name);
  const pricingModule={fillPricingSection:spy('fillPricingSection')};
  const skill=path.resolve(__dirname,'fixture-skill');
  const scope={engine,context:{expectedAccount:'fixture-account'},originalFlow:true,
    originalUploads:new Set(),uploadProblems:[],delivery:[],uploaded:[],
    path,skill,require:file=>{
      if(file==='./listing_completion.cjs')return {ensureContentEditors:async()=>{}};
      assert.equal(path.normalize(file),path.join(skill,'subskills/price-filler/scripts/fill_pricing_section.cjs'));
      return pricingModule;
    }};
  vm.createContext(scope);
  vm.runInContext(source.slice(start,end),scope);
  const page={evaluate:async()=>observed,locator:()=>{throw Error('original flow must not require legacy m7 locator');}};
  return {engine,pricingModule,page,calls,setObserved:value=>{observed=value;}};
}

test('the original Skill aborts before its first overlay or field operation for unknown/foreign accounts',async()=>{
  for(const observed of [[],['foreign-account']]){
    const s=setup(observed);
    await assert.rejects(s.engine.dismissFloatingOverlays(s.page),/身份尚未核验或与目标店铺不同/);
    assert.equal(s.calls.size,0);
  }
});

for(const name of entrypoints)test(name+' independently rejects unknown/foreign accounts before any original write',async()=>{
  for(const observed of [[],['foreign-account']]){
    const s=setup(observed);
    await assert.rejects(s.engine[name](s.page,'fixture-value'),/身份尚未核验或与目标店铺不同/,name);
    assert.equal(s.calls.size,0,name+' must never reach the original implementation');
  }
});

test('the separately imported original pricing module cannot write before account verification',async()=>{
  for(const observed of [[],['foreign-account']]){
    const s=setup(observed);
    await assert.rejects(s.pricingModule.fillPricingSection(s.page,{fields:{}}),/身份尚未核验或与目标店铺不同/);
    assert.equal(s.calls.size,0);
  }
});

test('matching accounts preserve original entrypoint arguments and results',async()=>{
  const s=setup(),value={fixture:'value'};
  for(const name of entrypoints){
    const result=await s.engine[name](s.page,value);
    assert.equal(result.name,name);
    assert.equal(result.args[0],s.page);
    assert.equal(result.args[1],value);
    assert.equal(s.calls.get(name),1);
  }
  const result=await s.pricingModule.fillPricingSection(s.page,value);
  assert.equal(result.name,'fillPricingSection');
  assert.equal(result.args[0],s.page);
  assert.equal(result.args[1],value);
  assert.equal(s.calls.get('fillPricingSection'),1);
});

test('a successful initial identity check never authorizes later writes after the account changes',async()=>{
  const s=setup();
  await s.engine.fillConfiguredField(s.page,'product_name','Fixture');
  assert.equal(s.calls.get('fillConfiguredField'),1);
  s.setObserved(['foreign-account']);
  for(const name of entrypoints){
    await assert.rejects(s.engine[name](s.page,'fixture-value'),/身份尚未核验或与目标店铺不同/,name);
  }
  await assert.rejects(s.pricingModule.fillPricingSection(s.page,{fields:{}}),/身份尚未核验或与目标店铺不同/);
  assert.equal(s.calls.size,1);
  assert.equal(s.calls.get('fillConfiguredField'),1);
});
