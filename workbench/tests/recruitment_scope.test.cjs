const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function page(){
  const events={};
  const p={URLSearchParams,Set,topicStore:'youhealth',topicData:{records:[],facets:{}},topicBusy:false,
    esc:String,icon:()=>'',head:()=>'',integrationDate:()=>'',
    document:{addEventListener:(name,fn)=>(events[name]??=[]).push(fn),querySelector:()=>null},
    window:{addEventListener(){}},current:'other',fetch:async()=>({ok:true,json:async()=>({store:'lifeworthcn',records:[]})})};
  vm.createContext(p);vm.runInContext(fs.readFileSync('recruitment_ui.js','utf8'),p);
  p.click=(dataset)=>{for(const fn of events.click)fn({target:{closest:()=>({dataset})}})};
  p.change=(id,value)=>{for(const fn of events.change)fn({target:{id,value,hasAttribute:()=>false}})};
  return p;
}

test('default and reset select main business scope with an explicit all-category option',()=>{
  const p=page();assert.equal(p.recruitQuery().get('category'),'__main__');
  vm.runInContext("recruitCategory='筋膜枪';reloadRecruit=()=>{}",p);
  p.click({action:'recruit-reset'});assert.equal(p.recruitQuery().get('category'),'__main__');
  const html=p.demandsPage();assert.match(html,/value="__main__" selected/);
  assert.match(html,/value=""\s*>全部已采集类目/);
});
test('switching business type restores main business scope',()=>{
  const p=page();vm.runInContext("recruitCategory='';reloadRecruit=()=>{}",p);
  p.click({action:'recruit-type',type:'CUSTOMIZATION_PRODUCT'});
  assert.equal(p.recruitQuery().get('category'),'__main__');
});
test('switching store restores main business scope',async()=>{
  const p=page();vm.runInContext("recruitCategory='';topicStore='lifeworthcn'",p);
  await p.loadTopics();assert.equal(p.recruitQuery().get('category'),'__main__');
});
test('scope counts distinguish category screening from platform qualification',()=>{
  const p=page();p.topicData.businessScope={retainedRecords:8,excludedRecords:12,totalRecords:20};
  assert.match(p.demandsPage(),/保留 8.*排除 12/);
  assert.match(p.demandsPage(),/平台资格另行检测/);
});

function hubPage(){
  const p=page();p.current='demands';p.location={hash:'#demands?view=topics&store=youhealth&business=CUSTOMIZATION_PRODUCT'};
  p.history={replaceState:(_a,_b,url)=>p.location.hash=url};p.executionData={products:[],jobs:[]};
  p.render=()=>p.demandsPage();
  p.fetch=async(url)=>({ok:true,json:async()=>({store:new URLSearchParams(url.split('?')[1]).get('store'),records:[],facets:{}})});
  vm.runInContext(fs.readFileSync('recruitment_hub.js','utf8'),p);return p;
}
test('real hub render preserves clicked business type instead of restoring stale URL',async()=>{
  const p=hubPage();p.click({action:'recruit-type',type:'HOT_PRODUCT'});await p.loadTopics();
  assert.equal(p.recruitQuery().get('businessType'),'HOT_PRODUCT');
  assert.match(p.location.hash,/business=HOT_PRODUCT/);
  assert.match(p.hubScopeLabel(),/主营营养品/);
});
test('real hub render preserves store switch instead of restoring stale URL',async()=>{
  const p=hubPage();vm.runInContext("topicStore='lifeworthcn'",p);await p.loadTopics();
  assert.equal(p.recruitQuery().get('store'),'lifeworthcn');assert.match(p.location.hash,/store=lifeworthcn/);
});
test('production-panel business selector updates route before rendering',async()=>{
  const p=hubPage();p.change('hubBusinessType','HOT_PRODUCT');await p.loadTopics();
  assert.equal(p.recruitQuery().get('businessType'),'HOT_PRODUCT');assert.match(p.location.hash,/business=HOT_PRODUCT/);
});
