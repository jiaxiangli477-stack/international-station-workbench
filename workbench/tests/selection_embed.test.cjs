const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function surface(viewer=false){
 const context={URL,URLSearchParams,Set,console,location:{href:'http://127.0.0.1:8796/#selection',origin:'http://127.0.0.1:8796',hash:'#selection'},history:{replaceState(){}},
 document:{addEventListener(){},getElementById(){return null}},window:{addEventListener(){}},teamViewOnly:()=>viewer,
 contextProduct:()=>null,head:()=>'',esc:x=>String(x??''),icon:()=>'',selectionHandoffPanel:()=>'',selectionChoiceError:'',selectionChoices:[{id:'c1',title:'Fixture candidate',form:'Powder',gate:'HOLD',markets:['US'],image:''}],executionData:null};
 vm.createContext(context);vm.runInContext(fs.readFileSync('selection_embed.js','utf8'),context);return context;
}
test('owner can select candidates with checkboxes instead of only a disabled dropdown',()=>{
 const s=surface(),html=s.selectionPage();
 assert.match(html,/data-selection-candidate="c1"/);
 assert.match(html,/data-action="selection-batch-preview"/);
 assert.doesNotMatch(html,/id="selectionHandoff"/);
});
test('viewer sees the full read-only app and a clear execution boundary',()=>{
 const s=surface(true),html=s.selectionPage();
 assert.equal(s.selectionWorkbenchURL(),'http://127.0.0.1:8796/selection-app/');
 assert.match(html,/只读|查看模式/);
 assert.doesNotMatch(html,/已有工作台 · 完整嵌入/);
});
test('owner embed also stays on the workbench origin and does not require port 8788',()=>{
 const s=surface(false);
 assert.equal(s.selectionWorkbenchURL(),'http://127.0.0.1:8796/selection-app/');
 assert.doesNotMatch(s.selectionPage(),/src="http:\/\/127\.0\.0\.1:8788/);
});
test('checking one candidate enables the owner image preview button without listing facts',()=>{
 const s=surface();const html=vm.runInContext("selectedCandidates.add('c1');selectionBatchPanel()",s);
 const button=html.match(/<button[^>]+data-action="selection-batch-preview"[^>]*>/)[0];
 assert.doesNotMatch(button,/\bdisabled\b/);
 assert.match(html,/已选 1 项 · 生图/);
});
test('selection progress shows current partial and pending images with their separate job and status',()=>{
 const s=surface();s.executionData={products:[{id:'p1',source:'selection:c1',title:'Fixture candidate',revision:3,stage:'images',
  visual:{revision:2,job:'old-complete',images:[{slot:'m2',file:'old.png'}]},
  visualPartial:{revision:3,job:'partial-job',status:'NEEDS_ATTENTION',images:[{slot:'m3',file:'partial.png',review:'PARTIAL'}]},
  visualPending:{revision:3,job:'pending-job',status:'RUNNING',images:[{slot:'m1',file:'pending.png',review:'PENDING'}]}}],jobs:[
  {id:'partial-job',product:'p1',status:'NEEDS_ATTENTION',progress:'1/6'},
  {id:'pending-job',product:'p1',status:'RUNNING',progress:'2/6'}]};
 s.executionURL=id=>'#workproduct?item='+id;s.productionStageText=()=> '图片制作中';s.executionLabels={NEEDS_ATTENTION:'需处理',RUNNING:'进行中'};
 const html=vm.runInContext("selectionProgressPanel()",s);
 assert.match(html,/partial\.png/);assert.match(html,/pending\.png/);
 assert.match(html,/m3/);assert.match(html,/m1/);
 assert.match(html,/需处理/);assert.match(html,/进行中/);
 assert.match(html,/partial-job/);assert.match(html,/pending-job/);
 assert.doesNotMatch(html,/old\.png/);
 assert.match(html,/未完成|部分/);
});
test('selection progress renders a packaging-only product without partial or pending assets',()=>{
 const s=surface();s.executionData={products:[{id:'p2',source:'selection:c1',title:'Fixture candidate',revision:1,stage:'packaging',
  packaging:{revision:1,job:'pack-job',images:[{slot:'pack',file:'pack.png'}]}}],jobs:[]};
 s.executionURL=id=>'#workproduct?item='+id;s.productionStageText=()=> '包装设计中';s.executionLabels={};
 const html=vm.runInContext("selectionProgressPanel()",s);
 assert.match(html,/pack\.png/);
 assert.match(html,/包装方向/);
});
test('selection progress refresh signature changes when current-revision image details change',()=>{
 const s=surface();s.executionData={products:[{id:'p3',source:'selection:c1',revision:2,
  visualPartial:{revision:2,job:'same-job',images:[{slot:'m1',file:'first.png',review:'PENDING'}]}}],jobs:[{id:'same-job',status:'RUNNING',progress:'1/6'}]};
 const first=vm.runInContext('selectionProgressSignature()',s);
 s.executionData.products[0].visualPartial.images[0].file='second.png';
 const second=vm.runInContext('selectionProgressSignature()',s);
 assert.notEqual(second,first);
 s.executionData.products[0].visualPartial.images[0].file='first.png';
 const third=vm.runInContext('selectionProgressSignature()',s);
 s.executionData.products[0].visualPartial.images[0].review='APPROVED';
 const fourth=vm.runInContext('selectionProgressSignature()',s);
 assert.notEqual(fourth,third);
});
