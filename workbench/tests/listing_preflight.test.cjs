const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {preflight,readbackMatches}=require('../listing_runner.cjs');
const skill=process.env.WORKBENCH_ATTRIBUTE_SKILL_ROOT||path.resolve(__dirname,'../../vendor/attribute-helper-v9.2.38/reviewed/alibaba-attribute-filler');
function manifest(){return {product_id:'fixture',category_dir:'supplement',fields:{product_name:'Protein Powder',
 main_ingredient:'Whey Protein',dosage_form:'Instant Powder',origin_country:'China',origin_province:'Guangdong',
 net_weight:'500g',protein_per_serving:'20g',unsuitable_audience:'Pregnant Women'}}}
test('installed category router is used instead of blindly trusting a requested category',()=>{
 const p=preflight(manifest(),{},skill);
 assert.equal(p.category,'202030102');
});
test('a recruitment leaf category conflict blocks filling',()=>{
 const p=preflight(manifest(),{recruitment:{requirements:[{kind:'category',name:'category',expected:['202029902']}]}},skill);
 assert.ok(p.blockers.some(x=>x.includes('叶子类目')));
});
test('the original fixed population cannot silently override a reviewed plan',()=>{
 const m=manifest();m.fields.unsuitable_audience='Newborn';
 const p=preflight(m,{},skill);
 assert.ok(p.blockers.some(x=>x.includes('unsuitable_audience')));
});
test('field readback never accepts 120g as a match for 20g',()=>{
 assert.equal(readbackMatches('20g','120g'),false);
 assert.equal(readbackMatches('20 g','20g'),true);
 assert.equal(readbackMatches('Powder','Powder; Powder'),true);
 assert.equal(readbackMatches('Powder','Powder; Gummy'),false);
});

test('preflight exposes the original Skill missing-field gate before any save attempt',()=>{
 const m=manifest();m.missing_required=['main_ingredient','net_weight'];
 const p=preflight(m,{},skill);
 assert.ok(p.blockers.some(x=>x.includes('main_ingredient')&&x.includes('net_weight')));
});

test('original Skill uses its own field locators without a separate CDN or field-ID prerequisite',()=>{
 const m=manifest();Object.assign(m.fields,{benefits:'Providing Energy',target_audience:'Adult',shelf_life:'24months',product_advantages:'Immune Support'});
 const pairs=[['Function','Providing Energy'],['Applicable People','Adult'],['Shelf-Life','24months'],['product benefits','Immune Support']];
 const p=preflight(m,{listingMechanism:'original-skill-v1',categoryOverride:{category:'supplement',categoryId:'202029902',source:'recruitment-requirement'},recruitment:{requirements:pairs.map(([name,value])=>({kind:'attribute',name,expected:[value]}))}},skill);
 assert.deepEqual(p.blockers,[]);assert.equal(p.category,'202029902');
 assert.equal(p.comparisons.filter(row=>row.matched).length,4);
 assert.equal(p.warnings.filter(row=>row.includes('原Skill页面定位')).length,4);
 assert.equal(p.recruitmentVerified,false);
});
