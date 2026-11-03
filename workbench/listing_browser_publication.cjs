'use strict';
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const MANAGER='https://i.alibaba.com/prod/product_manage';
const POST='https://post.alibaba.com/product/publish.htm';
const QUERY_HOST='hz-productposting.alibaba.com';
const QUERY_PATH='/product/managementproducts/asyQueryProductsList.do';
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const QUERY_ERRORS=['TAB_AMBIGUOUS','QUERY_CONTEXT_CHANGED','QUERY_HTTP_FAILED','LIST_NOT_SETTLED'];
const queryError=code=>Object.assign(new Error('publication query unavailable'),{publicationCode:code});
const tabKind=tab=>/^全部(?:[（(]\d+[)）])?$/.test(String(tab||'').replace(/\s/g,''))?'all':
  /^草稿(?:[（(]\d+[)）])?$/.test(String(tab||'').replace(/\s/g,''))?'draft':'';

function parseManagerRow(snapshot,productId,draftId){
  const unknown=reason=>({status:'unknown',status_text:'未知',reason,mapping_verified:false});
  if(!/^\d+$/.test(String(productId))||!/^\d+$/.test(String(draftId))||
      !snapshot||!tabKind(snapshot.tab)||!Array.isArray(snapshot.rows))return unknown('invalid_schema');
  const rows=snapshot.rows.filter(row=>row&&typeof row.id_text==='string'&&
    new RegExp('^ID:\\s*'+String(productId)+'$').test(row.id_text.trim()));
  if(!rows.length)return unknown('not_found');
  if(rows.length!==1)return unknown('multiple_rows');
  const row=rows[0];
  if(typeof row.status_text!=='string'||row.edit_conflict)return unknown('invalid_row');
  const lines=row.status_text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
  let edit;
  if(row.edit_url){try{edit=new URL(row.edit_url);}catch{return unknown('invalid_editor');}}
  if(edit&&(edit.origin!=='https://post.alibaba.com'||edit.pathname!=='/product/publish.htm'||
      edit.searchParams.getAll('itemId').length!==1||edit.searchParams.get('itemId')!==String(productId)))return unknown('foreign_editor');
  let status='unknown',label='未知';
  if(tabKind(snapshot.tab)==='draft'&&!lines.length&&edit&&
      edit.searchParams.getAll('pubAction').length===1&&edit.searchParams.get('pubAction')==='draft'){
    status='draft';label='草稿';
  }else if(tabKind(snapshot.tab)==='all'&&lines.length&&(!edit||edit.searchParams.get('pubAction')!=='draft')){
    if(lines.every(s=>s==='审核通过'||s==='已上架')&&lines.includes('已上架')){status='published';label='已上架';}
    if(lines.every(s=>s==='审核通过'||s==='已下架')&&lines.includes('已下架')){status='unpublished';label='已下架';}
  }
  if(status==='unknown')return unknown('unmapped_or_conflicting_status');
  return {status,status_text:label,reason:'',mapping_verified:true};
}

async function ownerIdentity(context,expected,draftId,categoryId){
  const page=await context.newPage();
  // Category selects a fresh owner probe only; it never proves this product's category.
  const editorUrl=categoryId?POST+'?catId='+encodeURIComponent(categoryId):
    POST+'?itemId='+encodeURIComponent(draftId)+'&pubAction=draft';
  try{
    await page.goto(editorUrl,{waitUntil:'domcontentloaded',timeout:60000});
    await page.waitForFunction(()=>!!window.GPF_GLOBAL_STORE?.json?.models?.global?.adminAliId,null,{timeout:30000});
    const identity=await page.evaluate(()=>{
      const model=window.GPF_GLOBAL_STORE?.json?.models?.global;
      return {owner:String(model?.adminAliId||''),nested_owner:String(model?.value?.adminAliId||'')};
    });
    if(page.url()!==editorUrl||identity.owner!==expected||
        identity.nested_owner&&identity.nested_owner!==expected)throw Error('publication identity mismatch');
    return {verified:true,account_id:identity.owner,nested_account_id:identity.nested_owner,
      source_url:page.url(),observed_at:new Date().toISOString()};
  }finally{await page.close().catch(()=>{});}
}

async function readSnapshot(page){
  return page.evaluate(()=>{
    const tab=document.querySelector('[role="tab"][aria-selected="true"]');
    const input=[...document.querySelectorAll('input[placeholder="请输入产品ID"]')].find(node=>node.getClientRects().length);
    const rows=[...document.querySelectorAll('.list-item.table-wrapper')].filter(node=>node.getClientRects().length).map(node=>{
      const matches=[...(node.innerText||'').matchAll(/(?:^|\n)\s*(ID:\s*\d+)\s*(?=\n|$)/g)].map(match=>match[1]);
      const urls=[...new Set([...node.querySelectorAll('a[href]')].map(a=>a.href).filter(href=>{
        try{const u=new URL(href);return u.hostname==='post.alibaba.com'&&u.pathname==='/product/publish.htm';}catch{return false;}
      }))];
      return {id_text:matches.length===1?matches[0]:'',status_text:node.querySelector('.product-status')?.innerText||'',
        edit_url:urls.length===1?urls[0]:'',edit_conflict:urls.length>1};
    });
    return {tab:tab?.innerText||'',queried_id:input?.value||'',rows};
  });
}

async function query(page,kind,productId,root){
  const label=kind==='all'?'全部':'草稿';
  const requestStatus=kind==='all'?'all':'sketch';
  const tab=page.getByRole('tab').filter({hasText:new RegExp('^\\s*'+label+'(?:[（(]\\s*\\d+\\s*[)）])?\\s*$')});
  const tabCount=await tab.count();
  let lastDiagnostic='';
  const diagnose=snapshot=>{
    const diagnostic=JSON.stringify({tab_count:tabCount,expected_kind:kind,observed_kind:tabKind(snapshot?.tab),
      queried_id_matches:snapshot?.queried_id===productId});
    if(diagnostic!==lastDiagnostic){fs.writeFileSync(path.join(root,'query-diagnostic.json'),diagnostic);lastDiagnostic=diagnostic;}
  };
  diagnose(null);
  if(tabCount!==1)throw queryError('TAB_AMBIGUOUS');
  await tab.click();
  const input=page.locator('input[placeholder="请输入产品ID"]:visible').first();
  await input.fill(productId);
  const pending=page.waitForResponse(response=>{
    try{
      const u=new URL(response.url()),params=u.searchParams;
      return u.origin==='https://'+QUERY_HOST&&u.pathname===QUERY_PATH&&response.request().method()==='GET'&&
        [['productId',productId],['status',requestStatus],['repositoryType','all'],['showType','onlyMarket']]
          .every(([key,value])=>params.getAll(key).length===1&&params.get(key)===value);
    }catch{return false;}
  },{timeout:30000});
  await page.getByRole('button',{name:'搜索',exact:true}).first().click();
  const response=await pending;
  if(!response.ok())throw queryError('QUERY_HTTP_FAILED');
  await response.finished();
  const responseParams=new URL(response.url()).searchParams;
  const responseEvidence={host:QUERY_HOST,path:QUERY_PATH,status:response.status(),method:response.request().method(),
    request_product_id:responseParams.get('productId'),request_status:responseParams.get('status'),
    repository_type:responseParams.get('repositoryType'),show_type:responseParams.get('showType')};
  let previous='',stable=0,contextMatches=false;
  const started=Date.now();
  while(Date.now()-started<15000){
    const snapshot=await readSnapshot(page),serialized=JSON.stringify(snapshot);
    diagnose(snapshot);
    contextMatches=tabKind(snapshot.tab)===kind&&snapshot.queried_id===productId;
    if(!contextMatches){stable=0;previous='';await page.waitForTimeout(300);continue;}
    stable=serialized===previous?stable+1:0;previous=serialized;
    if(stable>=3&&Date.now()-started>=1200)return {...snapshot,response:responseEvidence};
    await page.waitForTimeout(300);
  }
  throw queryError(contextMatches?'LIST_NOT_SETTLED':'QUERY_CONTEXT_CHANGED');
}

async function collect(requestFile){
  const root=path.dirname(path.resolve(requestFile));
  if(process.platform==='win32'&&path.parse(root).root.toUpperCase()!=='D:\\')throw Error('publication evidence must stay on D drive');
  let browser,page,before,after,snapshot,parsed,stage='request',failureStage='';
  try{
    const requestBytes=fs.readFileSync(requestFile),request=JSON.parse(requestBytes),target=request.target;
    if(path.basename(requestFile)!=='request.json'||!target||!/^\d+$/.test(target.product_id)||
      !/^\d+$/.test(target.draft_id)||!target.expected_account||!target.store||
      target.category_id!==undefined&&!/^[1-9][0-9]{0,24}$/.test(target.category_id)||
      request.collector_sha256!==hash(fs.readFileSync(__filename)))throw Error('invalid publication target');
    stage='cdp_connect';
    browser=await require('playwright').chromium.connectOverCDP('http://127.0.0.1:9322');
    const contexts=browser.contexts();
    if(contexts.length!==1)throw Error('publication browser context ambiguous');
    const context=contexts[0];
    stage='identity_before';
    before=await ownerIdentity(context,String(target.expected_account),String(target.draft_id),target.category_id);
    fs.writeFileSync(path.join(root,'identity-before.json'),JSON.stringify(before));
    try{
      stage='manager_navigation';
      page=await context.newPage();
      await page.goto(MANAGER,{waitUntil:'domcontentloaded',timeout:60000});
      const actualManager=new URL(page.url());
      fs.writeFileSync(path.join(root,'manager-navigation.json'),JSON.stringify({actual_origin:actualManager.origin,
        actual_path:actualManager.pathname,has_fragment:!!actualManager.hash}));
      if(actualManager.origin!=='https://i.alibaba.com'||actualManager.username||actualManager.password||
          actualManager.pathname.replace(/\/$/,'')!=='/prod/product_manage')throw Error('publication manager redirected');
      stage='all_query';
      const all=await query(page,'all',String(target.product_id),root);
      parsed=parseManagerRow(all,target.product_id,target.draft_id);
      snapshot={source_url:MANAGER,queries:[all]};
      if(parsed.status==='unknown'&&parsed.reason==='not_found'){
        stage='draft_query';
        const drafts=await query(page,'draft',String(target.product_id),root);
        snapshot.queries.push(drafts);parsed=parseManagerRow(drafts,target.product_id,target.draft_id);
      }
    }catch(error){failureStage=stage;throw error;}
    finally{
      stage='identity_after';
      try{
        after=await ownerIdentity(context,String(target.expected_account),String(target.draft_id),target.category_id);
        fs.writeFileSync(path.join(root,'identity-after.json'),JSON.stringify(after));
      }catch(error){failureStage=stage;throw error;}
    }
    stage='evidence_write';
    const snapshotBytes=Buffer.from(JSON.stringify(snapshot));
    fs.writeFileSync(path.join(root,'manager-dom.json'),snapshotBytes);
    const observation={source:{kind:'product_manager_row',method:'GET',url:MANAGER,evidence_root:root,
        collector_sha256:request.collector_sha256,python_sha256:request.python_sha256,request_sha256:hash(requestBytes),
        dom_sha256:hash(snapshotBytes),identity_before_sha256:hash(fs.readFileSync(path.join(root,'identity-before.json'))),
        identity_after_sha256:hash(fs.readFileSync(path.join(root,'identity-after.json')))},
      identity:{verified:true,account_id:String(target.expected_account)},observed_at:new Date().toISOString(),
      row:{item_id:String(target.product_id),draft_id:String(target.draft_id),status_field:'商品状态',status_text:parsed.status_text}};
    fs.writeFileSync(path.join(root,'observation.json'),JSON.stringify(observation,null,2));
    return observation;
  }catch(error){
    const errorName=['Error','TimeoutError','TypeError','SyntaxError'].includes(error?.name)?error.name:'Error';
    fs.writeFileSync(path.join(root,'error.json'),JSON.stringify({stage:failureStage||stage,error_name:errorName,
      ...(QUERY_ERRORS.includes(error?.publicationCode)?{error_code:error.publicationCode}:{})}));
    throw error;
  }finally{
    if(page)await page.close().catch(()=>{});
    if(browser)await browser.close();
  }
}

module.exports={parseManagerRow,collect};
if(require.main===module){
  collect(process.argv[2]).then(()=>process.stdout.write('publication observation collected\n'))
    .catch(()=>{process.stderr.write('publication read-only observation failed\n');process.exitCode=1;});
}
