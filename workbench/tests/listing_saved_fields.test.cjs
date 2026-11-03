const {test}=require('node:test'),assert=require('node:assert/strict');
const vm=require('node:vm');
const {readSavedListing,actualFieldReadback}=require('../listing_runner.cjs');
const context={listingMechanism:'original-skill-v1',allowMissingNetWeight:true};
test('blank unspecified original-Skill fields are not falsely counted as verified values',()=>{
 const rows=actualFieldReadback({product_name:'Fixture',net_weight:'',main_ingredient:'',dosage:'',target_audience:''},
  {product_name:'Fixture'},new Set(),context);
 assert.deepEqual(Object.keys(rows),['product_name']);assert.equal(rows.product_name.matched,true);
 assert.equal(actualFieldReadback({main_ingredient:'Protein'},{},new Set(),context).main_ingredient.matched,false);
});
test('the saved page provides its real productTitle control and category, without copying expected data',async()=>{
 const title={value:'Saved actual title'},global={catId:202029902,value:{catId:202029902}};
 const page={evaluate:async(fn,labels)=>vm.runInNewContext('('+fn.toString()+')(labels)',{
   labels,window:{GPF_GLOBAL_STORE:{json:{models:{global}}}},location:{search:'?itemId=123'},URLSearchParams,
   document:{getElementById:id=>id==='productTitle'?{tagName:'DIV'}:null,querySelectorAll:()=>[],
     querySelector:selector=>selector.startsWith('input#productTitle')?title:null}
 })};
 const actual=await readSavedListing(page,{});
 assert.equal(actual.fields.product_name,'Saved actual title');assert.equal(actual.category_id,'202029902');
 global.value.catId=999;assert.equal((await readSavedListing(page,{})).category_id,'');
});
