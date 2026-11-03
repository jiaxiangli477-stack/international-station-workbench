const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');
const source=fs.readFileSync('execution_ui.js','utf8');

test('quality module shows current-revision Skill diagnostics and keeps missing evidence on HOLD',()=>{
 const start=source.indexOf('function productQualityPanel('),end=source.indexOf('async function refreshProductQualityDiagnostics',start);
 assert(start>=0&&end>start,'quality panel renderer is present');
 const context={executionData:{products:[{id:'P-fixture',revision:3,title:'Fixture product'}]},
  productQualityDiagnostics:[{product_id:'P-fixture',revision:3,run_id:'a'.repeat(32),status:'completed',
   release_status:'HOLD',quality_score:2.1,missing_evidence:['market_evidence_missing','visual_analysis_missing']}],
  productQualityError:'',productQualityBusy:'',esc:x=>String(x??''),executionURL:id=>'#workproduct?item='+id};
 vm.createContext(context);vm.runInContext(source.slice(start,end),context);
 const html=vm.runInContext('productQualityPanel()',context);
 assert.match(html,/P-fixture · V3/);assert.match(html,/HOLD/);assert.match(html,/market_evidence_missing/);
 assert.match(html,/manifest_only/);assert.match(html,/data-action="quality-diagnose"/);
 assert.doesNotMatch(html,/pill[^>]*>建议发布/);
});

test('quality UI posts only an explicit current product revision to the local diagnostic route',()=>{
 assert.match(source,/fetch\('\/api\/product-quality\/diagnose'/);
 assert.match(source,/product_id:id,revision/);
 assert.match(source,/X-Workbench/);
});
