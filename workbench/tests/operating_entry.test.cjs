const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const root=path.join(__dirname,'..');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const execution=fs.readFileSync(path.join(root,'execution_ui.js'),'utf8');
const share=fs.readFileSync(path.join(root,'share.js'),'utf8');
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function scope(hash=''){
 const s={esc,URLSearchParams,icon:()=>'',flowURL:(key,id)=>'#'+key+(id?'?product='+encodeURIComponent(id):''),
  modules:[{id:'images'},{id:'listing'}],productionIssues:()=>[],
  executionURL:id=>'#workproduct?item='+encodeURIComponent(id),productionStageText:p=>p.stage,
  executionLabels:{QUEUED:'等待执行',RUNNING:'正在执行',SUCCESS:'产物已验证',NEEDS_ATTENTION:'需要处理'},
  executionData:null,executionError:'',location:{hash},integrationDate:x=>x||'未提供',
  panelHead:(a,b)=>`<h2>${a}</h2><p>${b}</p>`,head:(a,b)=>`<h1>${a}</h1><p>${b}</p>`};
 vm.createContext(s);
 const nav=app.slice(app.indexOf('const nav='),app.indexOf('const modules='));
 vm.runInContext(nav,s);
 const start=execution.indexOf('function operatingItems('),end=execution.indexOf('function executionOverview(',start);
 assert(start>=0,'missing operatingItems');vm.runInContext(execution.slice(start,end),s);
 return s;
}
test('seven navigation groups retain all eighteen original destinations and contextual links',()=>{
 const s=scope();const html=s.renderWorkbenchNav('images',{id:'P /1'});
 assert.equal((html.match(/data-nav-section=/g)||[]).length,7);
 assert.equal((html.match(/class="nav-item /g)||[]).length,18);
 for(const id of ['overview','analytics','inquiries','pipeline','tasks','followups','demands','quality','selection','images','listing','catalog','inbox','tools','modules','skills','team','settings'])assert.match(html,new RegExp('href="#'+id+'(?:[?\"])'));
 assert.match(html,/href="#images\?product=P%20%2F1"/);
 assert.equal((html.match(/aria-current="page"/g)||[]).length,1);
 assert.match(s.renderWorkbenchNav('workproduct',null),/data-nav-section="products"[^>]*open/);
});
test('attention aggregation keeps customer, product and machine identity separate, without copying state',()=>{
 const s=scope();const data={todos:[{id:'same',status:'OPEN',buyer:'Buyer'},{id:'same',status:'OPEN'},{id:'done',status:'DONE'}],products:[{id:'same',stage:'FACTS',title:'Product'},{id:'complete',stage:'COMPLETE'}],jobs:[{id:'same',status:'NEEDS_ATTENTION'},{id:'ok',status:'SUCCESS'},{id:'running',status:'RUNNING'}]};
 const before=JSON.stringify(data),q=s.operatingItems(data);
 assert.deepEqual(JSON.parse(JSON.stringify(Object.fromEntries(Object.entries(q).map(([k,v])=>[k,v.map(x=>x.id)])))),{customers:['same'],products:['same'],jobs:['same']});
 assert.equal(q.customers[0].href,'#followups?todo=same');
 assert.equal(q.products[0].href,'#workproduct?item=same');
 assert.equal(q.jobs[0].href,'#tasks?job=same');
 assert.equal(JSON.stringify(data),before);
});
test('loading, error and genuinely empty results are not conflated',()=>{
 const s=scope();assert.match(s.executionAttentionPanel(),/正在读取/);
 s.executionError='offline';assert.match(s.executionAttentionPanel(),/未连接/);
 s.executionData={todos:[],products:[],jobs:[]};s.executionError='';
 assert.match(s.executionAttentionPanel(),/暂无待核对的客户事项/);
});
test('attention preview is bounded with full original queues and untrusted fields escaped',()=>{
 const s=scope();s.executionData={todos:Array.from({length:9},(_,i)=>({id:String(i),status:'OPEN',buyer:'<img onerror=x>',note:'<script>x</script>'})),products:[],jobs:[]};
 const html=s.executionAttentionPanel();assert.equal((html.match(/class="operating-item"/g)||[]).length,6);
 assert.match(html,/全部 9 项/);assert(!html.includes('<img'));assert(!html.includes('<script>'));
});
test('task detail targets the exact job; missing IDs cannot fall back to another task',()=>{
 const s=scope('#tasks?job=second');s.executionData={jobs:[{id:'first',status:'SUCCESS'},{id:'second',status:'NEEDS_ATTENTION',progress:'<bad>'}]};
 assert.match(s.executionJobTarget(),/second/);assert(!s.executionJobTarget().includes('first'));
 assert.match(s.executionJobTarget(),/&lt;bad&gt;/);
 s.location.hash='#tasks?job=missing';assert.match(s.executionJobTarget(),/任务不存在/);
});
test('targeted customer links reveal the original item even when normal filters would hide it',()=>{
 const s=scope('#followups?todo=closed');s.executionData={todos:[{id:'closed',store:'YH',status:'DONE'}]};
 assert.equal(s.executionTarget('todo'),'closed');
 assert.equal(s.targetedFollowups(s.executionData.todos,'other','OPEN')[0].id,'closed');
 s.location.hash='#followups?todo=missing';assert.equal(s.targetedFollowups(s.executionData.todos,'','ALL').length,0);
});
test('all pending customers include in-progress items across stores, without completed records',()=>{
 const s=scope('#followups?pending=1');
 const rows=s.targetedFollowups([{id:'a',store:'A',status:'OPEN'},{id:'b',store:'B',status:'IN_PROGRESS'},{id:'c',store:'A',status:'DONE'}],'A','OPEN');
 assert.deepEqual(Array.from(rows,x=>x.id),['a','b']);
});
test('fallback customer guidance is explicitly unconfirmed and long machine logs are bounded',()=>{
 const s=scope();s.executionData={todos:[{id:'todo',status:'OPEN',buyer:'buyer'}],jobs:[{id:'job',status:'NEEDS_ATTENTION',progress:'x'.repeat(1000)}]};
 assert.match(s.executionAttentionPanel(),/待人工确认/);
 assert.equal(s.operatingItems(s.executionData).jobs[0].description.length,160);
});

test('product stage prioritizes the current workflow over a historical visual-review stage',()=>{
 const context=vm.createContext({});
 vm.runInContext(execution.slice(execution.indexOf('const productionStages='),execution.indexOf('function executionURL(')),context);
 const product={revision:5,stage:'VISUAL_REVIEW',recruitment:{},workflow:{revision:5,status:'NEEDS_INPUT'}};
 assert.equal(context.productionStageText(product),'待补资料');
 product.workflow.status='HERO_REVIEW';assert.equal(context.productionStageText(product),'首图待确认');
 product.workflow.revision=4;assert.equal(context.productionStageText(product),'征品图片待审核');
});

test('attention uses current product blockers and retains unresolved execution evidence',()=>{
 const s=scope();
 const data={products:[{id:'p',revision:5,stage:'VISUAL_REVIEW',workflowPlan:{next:'input',message:'补充草稿必填资料',gaps:['净含量']}}],jobs:[
  {id:'old-version',kind:'visual',product:'p',revision:4,status:'NEEDS_ATTENTION'},
  {id:'partial',kind:'visual',product:'p',revision:5,status:'NEEDS_ATTENTION',created:'2026-10-25T10:00:00Z'},
  {id:'complete',kind:'visual',product:'p',revision:5,status:'SUCCESS',created:'2026-10-26T10:00:00Z'},
  {id:'uncertain-save',kind:'listing',product:'p',revision:4,status:'NEEDS_ATTENTION',recoveryRequired:true},
  {id:'other-product',kind:'visual',product:'q',revision:1,status:'NEEDS_ATTENTION'}]};
 const q=s.operatingItems(data);
 assert.deepEqual(Array.from(q.jobs,x=>x.id),['uncertain-save','other-product']);
 assert.equal(q.products[0].description,'补充草稿必填资料');
 assert.match(q.products[0].note,/净含量/);
 assert.equal(data.jobs.length,5,'history remains available');
});

test('later inquiry success only supersedes the same store and exact period',()=>{
 const s=scope(),period={start:'2026-10-19',end:'2026-10-25'};
 const jobs=[{id:'failed',kind:'inquiry',store:'a',period,status:'NEEDS_ATTENTION',created:'2026-10-26T01:00:00Z'},
  {id:'ok',kind:'inquiry',store:'a',period,status:'SUCCESS',created:'2026-10-26T02:00:00Z'},
  {id:'other-store',kind:'inquiry',store:'b',period,status:'NEEDS_ATTENTION',created:'2026-10-26T01:00:00Z'},
  {id:'other-period',kind:'inquiry',store:'a',period:{start:'2026-10-12',end:'2026-10-18'},status:'NEEDS_ATTENTION',created:'2026-10-26T01:00:00Z'}];
 assert.deepEqual(Array.from(s.operatingItems({jobs}).jobs,x=>x.id),['other-store','other-period']);
});
test('product intelligence Skill Center state matches the local manifest-only diagnostic route and hold boundary',()=>{
 const row=app.match(/\{module:'quality',[^}]+\}/)?.[0]||'';
 assert.match(row,/statusLabel:'部分接入'/);
 assert.match(row,/manifest_only/);
 assert.match(row,/HOLD|缺证/);
 assert.doesNotMatch(row,/未发现可执行 Skill 入口|未接入/);
});
test('dashboard disclosure uses actual snapshot identity and does not claim audited values or invented attribution',()=>{
 const s=scope();const a=share.indexOf('function dashboardDecisionGuide('),b=share.indexOf('function sharedPanel(',a);
 assert(a>=0,'missing dashboardDecisionGuide');s.sharedPeriod=r=>r.start+' 至 '+r.end;
 vm.runInContext(share.slice(a,b),s);
 const html=s.dashboardDecisionGuide({fileName:'<unsafe>.html',start:'2026-10-12',end:'2026-10-18'},'YH');
 for(const text of ['2026-10-12','USD','CNY','未去重','近30天','内部','自然周','自然月'])assert(html.includes(text),text);
 assert(!html.includes('<unsafe>'));assert.match(html,/不等于/);assert.match(html,/面板内/);
 assert.equal(s.dashboardDecisionGuide(null,'YH'),'');
});
