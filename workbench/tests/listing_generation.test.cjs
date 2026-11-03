const test=require('node:test'),assert=require('node:assert/strict');
const {contentGenerationInput,finishContentGeneration,preflight}=require('../listing_runner.cjs');
const path=require('node:path');
test('original Skill generates pricing and fixed-field suggestions without inventing net weight',()=>{
 const {skillGeneratedSuggestions}=require('../listing_runner.cjs');
 const skill=path.resolve(__dirname,'../../vendor/attribute-helper-v9.2.38/reviewed/alibaba-attribute-filler');
 const engine=require(path.join(skill,'scripts/browser_runner.cjs'));
 const manifest={fields:{product_name:'Protein Powder',dosage_form:'Powder',protein_per_serving:'22g'}};
 const proposal=skillGeneratedSuggestions(manifest,skill,engine);
 assert.equal(proposal.kind,'DESIGN');assert.equal(proposal.pricing.tiers.length,3);
 assert.equal(proposal.fixed_fields.origin_country,'China');assert.equal(manifest.fields.net_weight,undefined);
 assert.equal(proposal.pricing.base,8.5);
});
test('offline generation accepts incomplete input while preserving warnings and original input',()=>{
 const original={fields:{product_name:'Protein Powder'},missing_required:['net_weight'],compliance_warnings:['review']};
 const draft=contentGenerationInput(original);
 assert.equal(draft.missing_required,undefined);assert.deepEqual(draft.compliance_warnings,['review']);
 assert.deepEqual(original.missing_required,['net_weight']);
});
test('unfilled or uncertain fields remain execution blockers after generation',()=>{
 const value={fields:{brand:'LIFEWORTH',net_weight:'TO_CONFIRM',dosage:''}};
 finishContentGeneration(value,['brand','net_weight','dosage']);
 assert.deepEqual(value.missing_required,['net_weight','dosage']);
});
test('visual-reference recruitment policy keeps platform mismatches as warnings without changing category',()=>{
 const skill=path.resolve(__dirname,'../../vendor/attribute-helper-v9.2.38/reviewed/alibaba-attribute-filler');
 const value={fields:{product_name:'Protein Powder',dosage_form:'Powder'},missing_required:['net_weight']};
 const result=preflight(value,{recruitmentMatchPolicy:'visual-reference',recruitment:{requirements:[{kind:'category',name:'category',expected:['202029902']}]}},skill);
 assert.equal(result.category,'202030102');assert.ok(result.warnings.some(x=>x.includes('叶子类目')));
 assert.ok(!result.blockers.some(x=>x.includes('叶子类目')));assert.ok(result.blockers.some(x=>x.includes('net_weight')));
 assert.equal(result.recruitmentVerified,false);
});
