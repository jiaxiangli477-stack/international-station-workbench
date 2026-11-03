const {test}=require('node:test'),assert=require('node:assert/strict');
const {assertReviewedContent}=require('../listing_runner.cjs');
test('execute cannot overwrite reviewed commercial text while fields remain equal',()=>{
 const before={fields:{product_name:'Synthetic'},selling_points:['Only supported copy'],faqs:[],company_intro:'Reviewed',pricing:{tiers:[]},lead_time:{},logistics:{}};
 for(const key of ['selling_points','faqs','company_intro','pricing','lead_time','logistics']){
  const after=structuredClone(before);after[key]='Unsupported generated claim';
  assert.throws(()=>assertReviewedContent(before,after),/已审核/);
 }
 assert.doesNotThrow(()=>assertReviewedContent(before,structuredClone(before)));
});
