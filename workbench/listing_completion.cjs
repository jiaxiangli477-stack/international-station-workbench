/* Full original-Skill content contract and an explicit same-draft repair. */
const fs=require('node:fs'),path=require('node:path');
const populated=value=>value!==undefined&&value!==null&&String(value).trim()!==''&&!String(value).includes('TO_CONFIRM');

function coverage(manifest,engine,config={},context={}){
  const skipped=new Set([...engine.SKIP_KEYS,...(config.skip_fields||[]),...(config.diff?.skip_fields||[]),...(config.diff?.removed_fields||[])]);
  const ordinary=['product_name','benefits','dosage_form','main_ingredient','origin_country','origin_province','brand','target_audience','unsuitable_audience','dosage','product_specification','shelf_life','storage_method','product_advantages','material_features','dietary_labels'];
  const required=[...new Set([...(config.required_fields||[]),...(String(config.category_id||'')==='100009042'?['product_name','brand']:ordinary)])].filter(k=>!skipped.has(k)&&!(k==='net_weight'&&context.listingMechanism==='original-skill-v1'&&context.allowMissingNetWeight===true));
  const missing=required.filter(k=>!populated(manifest.fields?.[k])).map(k=>'fields.'+k);
  const custom=manifest.custom_attributes||[],faqs=manifest.faqs||[],points=manifest.selling_points||[];
  if(custom.length!==10)missing.push('custom_attributes:10');
  for(const name of engine.CUSTOM_ATTRIBUTE_NAMES){const rows=custom.filter(r=>r.name===name);if(rows.length!==1||!populated(rows[0].value))missing.push('custom.'+name);}
  if(faqs.length!==8)missing.push('faqs:8');
  faqs.forEach((r,i)=>{if(!populated(r.question)||!populated(r.answer))missing.push('faq.'+(i+1));});
  if(points.length!==5||points.some(r=>!populated(r)))missing.push('selling_points:5');
  if(!populated(manifest.company_intro))missing.push('company_intro');
  return {status:missing.length?'BLOCKED':'READY',missing,ordinaryFilled:required.filter(k=>populated(manifest.fields?.[k])).length,ordinaryRequired:required.length,customAttributes:custom.length,faqs:faqs.length,sellingPoints:points.length};
}

function validateTarget(target,context){
  const url=new URL(target.draft_url);
  if(context.listingMechanism!=='original-skill-v1'||!context.expectedAccount||target.product!==context.product||target.revision!==context.revision||target.store!==context.store||!/^\d+$/.test(String(target.draft_id))||url.origin!=='https://post.alibaba.com'||url.pathname!=='/product/publish.htm'||url.searchParams.get('itemId')!==String(target.draft_id)||url.searchParams.get('pubAction')!=='draft')throw Error('已有草稿补全目标不一致');
  return String(target.draft_id);
}

async function ensureContentEditors(page,kind='company'){
  // The edit page mounts the original company/selling-point controls lazily.
  // Finding FAQ rows alone does not prove these other controls are ready.
  if(kind==='selling'){
    const jump=page.getByRole('button',{name:'去填写',exact:true});
    if(await jump.count()===1)await jump.click();
    await page.locator('#textDesc').scrollIntoViewIfNeeded({timeout:15000});
    await page.waitForSelector('#textDesc .text-area-list-editor[contenteditable="true"]',{state:'attached',timeout:25000});
  }else{
    const manual=page.getByText('手动填写新版',{exact:false}).first();
    if(await manual.count()&&await manual.isVisible())await manual.click();
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    await page.waitForSelector('textarea[placeholder*="介绍公司"]',{state:'attached',timeout:25000});
  }
}

async function complete(root,skill,manifest,context,engine,config){
  const target=JSON.parse(fs.readFileSync(path.join(root,'completion-target.json'),'utf8'));
  const draftId=validateTarget(target,context),content=coverage(manifest,engine,config,context);
  if(content.status!=='READY')throw Error('原Skill资料未补齐：'+content.missing.join('、'));
  const compliance=engine.checkCompliance(manifest.fields,manifest.custom_attributes,{FAQ:manifest.faqs,'公司介绍':manifest.company_intro,'商品卖点':manifest.selling_points});
  if(compliance.passed!==true)throw Error('原Skill合规检查未通过');
  const browser=await require('playwright').chromium.connectOverCDP('http://127.0.0.1:9322',{timeout:30000});
  let page;
  const report={status:'STARTED',draft_id:draftId,coverage:content,fields:[],imageWritesInvoked:false,published:false};
  const saveReport=()=>fs.writeFileSync(path.join(root,'completion-report.json'),JSON.stringify(report,null,2));
  async function identity(){
    const observed=await page.evaluate(()=>{const m=window.GPF_GLOBAL_STORE?.json?.models?.global;return {url:location.href,owner:String(m?.adminAliId||m?.value?.adminAliId||''),category:String(m?.catId||m?.value?.catId||'')};});
    const url=new URL(observed.url);
    if(observed.owner!==String(context.expectedAccount)||url.origin!=='https://post.alibaba.com'||url.pathname!=='/product/publish.htm'||url.searchParams.get('itemId')!==draftId||observed.category!==String(config.category_id))throw Error('补全前账号、草稿ID或类目不一致');
  }
  try{
    page=await browser.contexts()[0].newPage();await page.goto(target.draft_url,{waitUntil:'domcontentloaded',timeout:60000});
    await page.waitForFunction(()=>!!window.GPF_GLOBAL_STORE?.json?.models?.global?.adminAliId,null,{timeout:30000});await identity();saveReport();
    const plan=engine.buildExecutionPlan(manifest);
    const reader=require('./listing_runner.cjs');
    const before=await reader.readSavedListing(page,engine.FIELD_LABELS);
    for(const key of engine.FIELD_FILL_ORDER){
      if(engine.SKIP_KEYS.has(key)||!populated(plan.fields[key]))continue;
      if(key==='net_weight'&&context.allowMissingNetWeight===true)continue;
      if(reader.readbackMatches(plan.fields[key],before.fields[key])){report.fields.push({key,status:'already_matched',actual:before.fields[key]});continue;}
      await identity();const result=await engine.fillConfiguredField(page,key,plan.fields[key]);report.fields.push(result);saveReport();
      if(String(result.status).startsWith('skipped')||result.status==='error')throw Error('原Skill字段未填写：'+key);
    }
    await identity();report.custom=await engine.fillCustomAttributes(page,plan.custom_attributes);
    await identity();await ensureContentEditors(page);await engine.fillCompanyIntroAndFAQ(page,manifest.company_intro,manifest.faqs);
    await identity();await ensureContentEditors(page,'selling');report.selling_points=await engine.fillSellingPoints(page,manifest.selling_points);
    await identity();report.save=await engine.saveDraft(page);saveReport();
    if(report.save.status!=='draft_saved')throw Error('原Skill未保存草稿');
    report.verification=await engine.verifySavedDraft(page,manifest,{company_intro:manifest.company_intro});
    await identity();
    if(report.verification.status!=='verified'||report.verification.missing_required?.length||report.verification.structure_mismatches?.length||report.verification.checks?.some(row=>row.matched===false))throw Error('原Skill保存后完整内容回读未通过');
    const observed=await reader.readSavedListing(page,engine.FIELD_LABELS);
    report.fieldsReadback=reader.actualFieldReadback(manifest.fields,observed.fields,engine.SKIP_KEYS,context);
    if(Object.values(report.fieldsReadback).some(row=>!row.matched||!row.actual))throw Error('完整普通属性实际回读未通过');
    report.status='completed';report.verifiedAt=new Date().toISOString();saveReport();
    await page.screenshot({path:path.join(root,'completed-draft.png'),fullPage:true});
  }catch(error){report.status='NEEDS_ATTENTION';report.error=String(error.message).slice(0,300);
    if(page)report.editorDiagnostics=await page.evaluate(()=>Array.from(document.querySelectorAll('textarea,[contenteditable]')).map(e=>({tag:e.tagName,cls:e.className,placeholder:e.getAttribute('placeholder')?.slice(0,60),length:(e.value||e.textContent||'').length}))).catch(()=>[]);
    saveReport();throw error;}
  finally{if(page)await page.close().catch(()=>{});await browser.close();}
}

module.exports={coverage,validateTarget,ensureContentEditors,complete};
