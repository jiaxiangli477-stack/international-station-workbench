const test=require('node:test'),assert=require('node:assert/strict');
const path=require('node:path');
const engine=require(path.resolve(__dirname,'../../vendor/attribute-helper-v9.2.38/reviewed/alibaba-attribute-filler/scripts/browser_runner.cjs'));
const completion=require('../listing_completion.cjs');
const {coverage,validateTarget}=completion;
const context={listingMechanism:'original-skill-v1',allowMissingNetWeight:true,product:'p',revision:6,store:'youhealth',expectedAccount:'test-owner'};
function full(){return {fields:Object.fromEntries(['product_name','benefits','dosage_form','main_ingredient','origin_country','origin_province','brand','target_audience','unsuitable_audience','dosage','product_specification','shelf_life','storage_method','product_advantages','material_features','dietary_labels'].map(k=>[k,'Fixture'])),custom_attributes:engine.CUSTOM_ATTRIBUTE_NAMES.map(name=>({name,value:'Fixture'})),faqs:Array.from({length:8},(_,i)=>({question:'Question '+i,answer:'Answer '+i})),selling_points:Array(5).fill('Fixture'),company_intro:'Fixture'};}
test('sparse manifest cannot pass merely because nonempty fields match',()=>{
 const result=coverage({fields:{dosage_form:'Gummy'},custom_attributes:[],faqs:[{},{}]},engine,{},context);
 assert.equal(result.status,'BLOCKED');assert.ok(result.missing.includes('fields.main_ingredient'));assert.ok(result.missing.includes('custom_attributes:10'));assert.ok(result.missing.includes('faqs:8'));
});
test('complete original flow allows only explicitly permitted net-weight blank',()=>{
 const m=full();m.fields.net_weight='';assert.equal(coverage(m,engine,{required_fields:['net_weight']},context).status,'READY');
 assert.ok(coverage(m,engine,{required_fields:['net_weight']},{...context,allowMissingNetWeight:false}).missing.includes('fields.net_weight'));
 m.fields.main_ingredient='TO_CONFIRM';assert.equal(coverage(m,engine,{},context).status,'BLOCKED');
});
test('all ten named custom attributes and eight nonempty FAQs must exist',()=>{
 const m=full();m.custom_attributes[9].name=m.custom_attributes[0].name;m.faqs[7].answer='';
 const result=coverage(m,engine,{},context);assert.equal(result.status,'BLOCKED');assert.ok(result.missing.includes('custom.Sample Support'));assert.ok(result.missing.includes('faq.8'));
});
test('same-draft update rejects alternate targets and requires draft edit URL',()=>{
 const target={product:'p',revision:6,store:'youhealth',draft_id:'123',draft_url:'https://post.alibaba.com/product/publish.htm?itemId=123&pubAction=draft'};
 assert.equal(validateTarget(target,context),'123');
 for(const bad of [{...target,store:'other'},{...target,draft_id:'456'},{...target,draft_url:'https://post.alibaba.com/product/publish.htm?itemId=123'},{...target,revision:7}])assert.throws(()=>validateTarget(bad,context));
});
test('content editors must mount after scrolling before the original filler is invoked',async()=>{
 const calls=[];
 const manual={count:async()=>1,isVisible:async()=>true,click:async()=>calls.push('manual')};
 const page={getByText:()=>({first:()=>manual}),getByRole:()=>({count:async()=>1,click:async()=>calls.push('jump')}),locator:()=>({scrollIntoViewIfNeeded:async()=>calls.push('section')}),evaluate:async()=>calls.push('scroll'),waitForSelector:async(selector)=>calls.push(selector)};
 await completion.ensureContentEditors(page);
 assert.equal(calls[0],'manual');assert.equal(calls[1],'scroll');assert.ok(calls.some(x=>x.includes('介绍公司')));
 calls.length=0;await completion.ensureContentEditors(page,'selling');assert.deepEqual(calls.slice(0,2),['jump','section']);assert.ok(calls[2].includes('text-area-list-editor'));
 await assert.rejects(completion.ensureContentEditors({...page,waitForSelector:async()=>{throw Error('not mounted')}}),/not mounted/);
});
