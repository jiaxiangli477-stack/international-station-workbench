'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
let collector={};
try{collector=require('../listing_browser_publication.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const parse=(snapshot)=>{
  assert.equal(typeof collector.parseManagerRow,'function','missing pure manager parser');
  return collector.parseManagerRow(snapshot,'12345','12345');
};
const row=(status='审核通过\n已上架')=>({id_text:'ID: 12345',status_text:status,edit_url:''});
const draft=()=>({id_text:'ID: 12345',status_text:'',edit_url:'https://post.alibaba.com/product/publish.htm?itemId=12345&pubAction=draft'});

test('all tab exact ID and explicit status cell proves published or unpublished',()=>{
  assert.equal(parse({tab:'全部(944)',rows:[row()]}).status,'published');
  assert.equal(parse({tab:'全部(944)',rows:[row('审核通过\n已下架')]}).status,'unpublished');
});
test('draft requires selected draft tab and the exact draft editor identity',()=>{
  assert.equal(parse({tab:'草稿(46)',rows:[draft()]}).status,'draft');
  for(const change of [{tab:'全部(944)'},{edit_url:'https://post.alibaba.com/product/publish.htm?itemId=999&pubAction=draft'},
      {edit_url:'https://example.com/product/publish.htm?itemId=12345&pubAction=draft'},
      {edit_url:'https://post.alibaba.com/product/publish.htm?itemId=12345&pubAction=publish'}]){
    assert.equal(parse({tab:change.tab||'草稿(46)',rows:[{...draft(),...change}]}).status,'unknown');
  }
});
test('audit pending rejected unfamiliar and contradictory status remain unknown',()=>{
  for(const status of ['审核中','审核不通过','已上架\n已下架','审核中\n已上架','已发布','100','']){
    assert.equal(parse({tab:'全部(944)',rows:[row(status)]}).status,'unknown');
  }
  assert.equal(parse({tab:'草稿(46)',rows:[row()]}).status,'unknown');
  assert.equal(parse({tab:'全部(944)',rows:[{...draft(),status_text:'已上架'}]}).status,'unknown');
});
test('foreign IDs multirow schema mismatch and substring IDs never pass',()=>{
  for(const snapshot of [{tab:'全部(944)',rows:[{...row(),id_text:'ID: 912345'}]},
      {tab:'全部(944)',rows:[row(),row()]},{tab:'全部(944)',rows:[{...row(),id_text:'ID: 12345\nID: 999'}]},
      {tab:'上架(846)',rows:[row()]},{tab:'全部(944)',rows:'claimed published'},{}]){
    assert.equal(parse(snapshot).status,'unknown');
  }
});
test('empty all result is distinguished from an unresolved matching row',()=>{
  assert.equal(parse({tab:'全部(944)',rows:[]}).reason,'not_found');
  assert.notEqual(parse({tab:'全部(944)',rows:[row('审核中')]}).reason,'not_found');
});

test('collector opens only its own pages, registers query before search, and closes them on success or identity failure',async()=>{
  const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),Module=require('node:module');
  const base=path.resolve('D:/Codex/国际站工作台/repair-chain-20261101/browser-publication');
  fs.mkdirSync(base,{recursive:true});
  for(const {failAfter,category} of [{failAfter:false,category:'202029902'},{failAfter:false,category:''},{failAfter:true,category:''}]){
    const root=fs.mkdtempSync(path.join(base,'lifecycle-'));
    const calls=[],pages=[];
    const context={async newPage(){
      const index=pages.length;
      const page={tab:'全部(944)',queried:'',closed:false,
        async goto(url){
          calls.push(['goto',url]);
          if(category&&url.includes('pubAction=draft'))throw Error('published product has no draft editor');
          this.address=url==='https://i.alibaba.com/prod/product_manage'?url+'/#/products':url;
        },url(){return this.address;},
        async waitForFunction(){},async evaluate(){
          if(index===1){
            this.reads=(this.reads||0)+1;
            return {tab:this.reads<3?'草稿(46)':this.tab,queried_id:this.reads<3?'':this.queried,rows:[row()]};
          }
          return {owner:failAfter&&index===2?'other':'owner-fixture',nested_owner:''};
        },async close(){this.closed=true;calls.push(['close-page',index]);},
        getByRole(role,options){
          if(role==='tab')return {filter:()=>({count:async()=>1,click:async()=>calls.push(['tab'])})};
          assert.deepEqual(options,{name:'搜索',exact:true});
          return {first:()=>({click:async()=>calls.push(['search'])})};
        },locator(selector){assert.equal(selector,'input[placeholder="请输入产品ID"]:visible');
          return {first:()=>({fill:async value=>{this.queried=value;calls.push(['input',value]);}})};
        },async waitForResponse(predicate){
          calls.push(['listen']);
          const queryUrl='https://hz-productposting.alibaba.com/product/managementproducts/asyQueryProductsList.do?productId=12345&repositoryType=all&status=all&showType=onlyMarket';
          const response={url:()=>queryUrl,request:()=>({method:()=> 'GET'}),ok:()=>true,status:()=>200,finished:async()=>{}};
          assert.equal(predicate({...response,url:()=>queryUrl.replace('productId=12345','productId=999')}),false);
          assert.equal(predicate({...response,url:()=>queryUrl.replace('status=all','status=sketch')}),false);
          assert.equal(predicate(response),true);return response;
        },async waitForTimeout(ms){await new Promise(resolve=>setTimeout(resolve,ms));}};
      pages.push(page);return page;
    }};
    const load=Module._load;
    Module._load=function(name,...args){if(name==='playwright')return {chromium:{connectOverCDP:async endpoint=>{
      assert.equal(endpoint,'http://127.0.0.1:9322');return {contexts:()=>[context],close:async()=>calls.push(['disconnect'])};
    }}};return load.call(this,name,...args);};
    try{
      const digest=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
      const request=path.join(root,'request.json');
      fs.writeFileSync(request,JSON.stringify({target:{store:'fixture',product_id:'12345',draft_id:'12345',expected_account:'owner-fixture',...(category?{category_id:category}:{})},
        run_id:'fixture-run',collector_sha256:digest(path.join(__dirname,'../listing_browser_publication.cjs')),
        python_sha256:digest(path.join(__dirname,'../listing_browser_publication.py'))}));
      if(failAfter){
        await assert.rejects(collector.collect(request));assert.equal(fs.existsSync(path.join(root,'observation.json')),false);
        assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'error.json'))),{stage:'identity_after',error_name:'Error'});
      }
      else{
        const result=await collector.collect(request);assert.equal(result.row.status_text,'已上架');
        assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'manager-navigation.json'))),{
          actual_origin:'https://i.alibaba.com',actual_path:'/prod/product_manage/',has_fragment:true});
        const snapshot=JSON.parse(fs.readFileSync(path.join(root,'manager-dom.json')));
        assert.equal(snapshot.queries[0].response.request_product_id,'12345');
        assert.equal(snapshot.queries[0].response.request_status,'all');
      }
      assert.equal(pages.length,3);assert.equal(pages.every(page=>page.closed),true);
      assert.equal(calls.findIndex(row=>row[0]==='listen')<calls.findIndex(row=>row[0]==='search'),true);
      assert.equal(calls.filter(row=>row[0]==='disconnect').length,1);
      const ownerUrl=category?'https://post.alibaba.com/product/publish.htm?catId='+category:
        'https://post.alibaba.com/product/publish.htm?itemId=12345&pubAction=draft';
      assert.equal(calls.filter(row=>row[0]==='goto'&&row[1]===ownerUrl).length,2);
    }finally{
      Module._load=load;
      assert.equal(root.startsWith(base+path.sep),true);fs.rmSync(root,{recursive:true,force:true});
    }
  }
});
