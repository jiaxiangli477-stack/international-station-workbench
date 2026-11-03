const {test}=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const runner=require('../listing_runner.cjs');
const fs=require('node:fs'),vm=require('node:vm');
const skill=process.env.WORKBENCH_ATTRIBUTE_SKILL_ROOT||path.resolve(__dirname,'../../vendor/attribute-helper-v9.2.38/reviewed/alibaba-attribute-filler');
const allowed={listingMechanism:'original-skill-v1',allowMissingNetWeight:true};
function manifest(){return {product_id:'synthetic',fields:{product_name:'Synthetic Protein Gummies',main_ingredient:'Synthetic Protein',
 dosage_form:'Gummy',origin_country:'China',origin_province:'Guangdong',net_weight:'',protein_per_serving:'20g',unsuitable_audience:'Pregnant Women',brand:'LIFEWORTH',benefits:'Providing Energy',target_audience:'Adult',dosage:'20g Protein Per Serving',product_specification:'Resealable Pouch',shelf_life:'24months',storage_method:'Store cool and dry',product_advantages:'muscle growth',material_features:'Protein',dietary_labels:'Standard Formula'},custom_attributes:require(path.join(skill,'scripts/browser_runner.cjs')).CUSTOM_ATTRIBUTE_NAMES.map(name=>({name,value:'Synthetic'})),faqs:Array.from({length:8},(_,i)=>({question:'Synthetic '+i,answer:'Synthetic'})),selling_points:Array(5).fill('Synthetic'),company_intro:'Synthetic',missing_required:['net_weight']};}
test('only exact original-Skill user authorization enables the vendor controlled-draft argument',()=>{
 assert.equal(runner.allowMissingNetWeight(allowed),true);
 assert(runner.originalSkillRuntimeArgs(allowed).includes('--allow-missing-net-weight'));
 for(const context of [{},{...allowed,allowMissingNetWeight:1},{...allowed,listingMechanism:'legacy'}]){
  assert.equal(runner.allowMissingNetWeight(context),false);
  assert(!runner.originalSkillRuntimeArgs(context).includes('--allow-missing-net-weight'));
 }
});
test('authorized empty net weight passes only its local gate while other required/compliance failures remain',()=>{
 const m=manifest(),before=JSON.stringify(m),context={...allowed,categoryOverride:{category:'supplement',categoryId:'202029902',source:'recruitment-requirement'}};
 assert.deepEqual(runner.preflight(m,context,skill).blockers,[]);
 assert(runner.preflight(m,{...context,allowMissingNetWeight:false},skill).blockers.some(x=>x.includes('net_weight')));
 assert.equal(JSON.stringify(m),before);
 m.fields.main_ingredient='';m.missing_required.push('main_ingredient');
 assert(runner.preflight(m,context,skill).blockers.some(x=>x.includes('main_ingredient')));
 m.fields.main_ingredient='Synthetic Protein';m.missing_required=['net_weight'];m.compliance_warnings=['review'];
 assert(runner.preflight(m,context,skill).blockers.some(x=>x.includes('compliance')));
});
test('authorized generation keeps net weight blank and retains every other missing field',()=>{
 const m={fields:{net_weight:'35g',main_ingredient:''}};
 runner.finishContentGeneration(m,['net_weight','main_ingredient'],allowed);
 assert.equal(m.fields.net_weight,'');assert.deepEqual(m.missing_required,['main_ingredient']);
 const normal={fields:{net_weight:''}};runner.finishContentGeneration(normal,['net_weight'],{});
 assert.deepEqual(normal.missing_required,['net_weight']);
});
test('intentional blank readback is omitted rather than marked verified and unexpected weight is rejected',()=>{
 const expected={product_name:'Synthetic',net_weight:''};
 const actual=runner.actualFieldReadback(expected,{product_name:'Synthetic',net_weight:''},new Set(),allowed);
 assert.equal(actual.product_name.matched,true);assert(!('net_weight' in actual));
 for(const value of ['35g','0',0])assert.throws(()=>runner.actualFieldReadback(expected,{net_weight:value},new Set(),allowed),/净重.*留空/);
 const normal=runner.actualFieldReadback(expected,{product_name:'Wrong'},new Set(),allowed);
 assert.equal(normal.product_name.matched,false);
 const noPermission=runner.actualFieldReadback(expected,{net_weight:''},new Set(),{});
 assert.equal(noPermission.net_weight.matched,false);
});
test('the unmodified vendor controlled-draft switch downgrades only its net-weight diagnostic',()=>{
 const source=fs.readFileSync(path.join(skill,'scripts/run_all.cjs'),'utf8');
 const start=source.indexOf('const allowMissingNetWeight = Object.prototype.hasOwnProperty.call(args');
 const end=source.indexOf('const productId = manifest.product_id',start);
 assert(start>=0&&end>start);
 const scope={args:{'allow-missing-net-weight':'1'},console:{warn(){}},contentCsv:{blockers:[{key:'net_weight_unconfirmed'},{key:'other_required'}],warnings:[],status:'blocked'}};
 vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
 assert.equal(scope.contentCsv.blockers.length,1);assert.equal(scope.contentCsv.blockers[0].key,'other_required');
 assert.equal(scope.contentCsv.warnings[0].key,'net_weight_unconfirmed');assert.equal(scope.contentCsv.status,'blocked');
});
