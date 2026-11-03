const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../execution_ui.js'),'utf8');
const start=source.indexOf('async function refreshExecution()');
const end=source.indexOf('async function executionCommand(',start);

function context(current,initial=null){
 let renders=0;
 const data={stores:[{id:'lifeworthcn'},{id:'youhealth'}]};
 const scope={current,executionData:initial,executionError:'',executionDirty:false,executionPendingRender:false,
  fetch:async()=>({ok:true,json:async()=>data}),render:()=>{renders++},
  document:{activeElement:null,body:{classList:{contains:()=>false}}}};
 vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
 return {scope,renders:()=>renders};
}

test('initial selection data load redraws the page so target shops become selectable',async()=>{
 const c=context('selection');await c.scope.refreshExecution();
 assert.equal(c.scope.executionData.stores.length,2);
 assert.equal(c.renders(),1);
});
test('later selection polling preserves the embedded research page',async()=>{
 const c=context('selection',{stores:[]});await c.scope.refreshExecution();
 assert.equal(c.renders(),0);
});
test('initial inquiry data load still redraws the report selection',async()=>{
 const c=context('inquiries');await c.scope.refreshExecution();
 assert.equal(c.renders(),1);
});
