/* Workbench evidence around the unmodified Skill; never an uploader or saver. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const activePages = new WeakSet();
const GROUP_VALUES = [110,170,200,300,350,400,450,500,550,600,650];
const SELECTORS = Object.freeze({mainInput:'.upload-select-inner input[type="file"]',
  mainItem:'.image-upload-list-item',detailUpload:'.next-upload.upload-image'});

class EvidenceError extends Error {
  constructor(code, message) { super(message); this.name='EvidenceError'; this.code=code; }
}
const fail = (code,message) => { throw new EvidenceError(code,message); };
const unverified = () => fail('UPLOAD_EVIDENCE_UNVERIFIED','平台上传请求/响应尚未形成唯一文件证据，已阻止保存');

function capability() {
  return {adapterVersion:1,implemented:true,canAttemptCapture:true,ready:false,liveVerified:false,
    acceptance:'awaiting-live-request-response-and-section-dom',selectors:SELECTORS,
    required:['actual multipart binary bytes','one file per response with one resource',
      'trusted Alibaba upload origin and image CDN','unique section containers and current saved itemId']};
}

function trustedUpload(value) {
  try {
    const url=new URL(value);
    return url.protocol==='https:' && !url.username && !url.password && (!url.port || url.port==='443') &&
      (url.hostname==='alibaba.com' || url.hostname.endsWith('.alibaba.com') ||
       url.hostname==='alicdn.com' || url.hostname.endsWith('.alicdn.com'));
  } catch { return false; }
}

function canonicalResourceUrl(value) {
  if (typeof value!=='string' || !/^(https:)?\/\//.test(value)) unverified();
  let url;
  try { url=new URL(value.startsWith('//')?'https:'+value:value); } catch { unverified(); }
  if (url.protocol!=='https:' || url.username || url.password || url.search || url.hash ||
      url.port && url.port!=='443' ||
      !(url.hostname==='alicdn.com' || url.hostname.endsWith('.alicdn.com')) ||
      !/\.(?:png|jpe?g|webp|gif|avif|bmp)(?:$|_)/i.test(url.pathname)) unverified();
  return url.href;
}

async function multipartFiles(body, contentType) {
  if (!Buffer.isBuffer(body) || !body.length || body.length>64*1024*1024 ||
      typeof contentType!=='string' || !/^multipart\/form-data\s*;/i.test(contentType)) unverified();
  let form;
  try { form=await new Response(body,{headers:{'Content-Type':contentType}}).formData(); }
  catch { unverified(); }
  const files=[];
  for (const [field,value] of form) {
    if (!value || typeof value.arrayBuffer!=='function' || typeof value.name!=='string') continue;
    const bytes=Buffer.from(await value.arrayBuffer());
    const offset=body.indexOf(bytes);
    if (!bytes.length || offset<0 || body.indexOf(bytes,offset+1)>=0 || !value.name ||
        /[\\/\r\n\0]/.test(value.name)) unverified();
    files.push({field,filename:value.name,sha256:hash(bytes),size:bytes.length,bodyOffset:offset});
  }
  // The actual platform batch response schema is not verified. Never zip files to URLs by order.
  if (files.length!==1) unverified();
  return files;
}

function responseResource(bytes, file) {
  if (!Buffer.isBuffer(bytes) || !bytes.length || bytes.length>1024*1024) unverified();
  let data;
  try { data=JSON.parse(bytes.toString('utf8')); } catch { unverified(); }
  // Unknown success envelopes require a reviewed real sample; HTTP 200 alone is insufficient.
  if (!data || data.success!==true) unverified();
  const resources=[];
  let visited=0;
  function visit(node,at,depth) {
    if (++visited>1000 || depth>10) unverified();
    if (!node || typeof node!=='object') return;
    if (Array.isArray(node)) { node.forEach((row,index)=>visit(row,at.concat(index),depth+1)); return; }
    const urls=Object.keys(node).filter(key=>['url','imageUrl','fileUrl','picUrl','originalUrl'].includes(key));
    for (const key of urls) {
      const url=canonicalResourceUrl(node[key]);
      const named=node.filename ?? node.fileName;
      if (named!==undefined && named!==file.filename || node.sha256!==undefined && node.sha256!==file.sha256) unverified();
      const ids=['assetId','imageId'].filter(name=>node[name]!==undefined && node[name]!==null && node[name]!=='');
      if (ids.length>1 && String(node[ids[0]])!==String(node[ids[1]])) unverified();
      const id=ids.length?String(node[ids[0]]):url;
      if (ids.length && !/^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/.test(id)) unverified();
      resources.push({url,assetId:id,identityKind:ids.length?'platform-asset-id':'platform-url',
        responseUrlPath:at.concat(key),responseIdentityPath:ids.length?at.concat(ids[0]):at.concat(key)});
    }
    for (const [key,value] of Object.entries(node)) if (value && typeof value==='object') visit(value,at.concat(key),depth+1);
  }
  visit(data,[],0);
  const unique=[...new Map(resources.map(row=>[row.url+'\0'+row.assetId,row])).values()];
  if (unique.length!==1) unverified();
  return unique[0];
}

async function verifyUploadReplay(record, {requestBody,contentType,responseBody}) {
  if (hash(requestBody)!==record.requestHash || hash(responseBody)!==record.responseHash) unverified();
  const [file]=await multipartFiles(requestBody,contentType),resource=responseResource(responseBody,file);
  if (file.sha256!==record.sha256 || file.filename!==record.filename ||
      resource.assetId!==record.assetId || resource.identityKind!==record.identityKind || resource.url!==record.url) unverified();
  return true;
}

function expectedFiles(root, delivery, files) {
  if (!Array.isArray(files) || !files.length || !Array.isArray(delivery)) unverified();
  const base=path.resolve(root);
  const rows=files.map((file,index)=>{
    const absolute=path.resolve(file),relative=path.relative(base,absolute);
    const matches=delivery.filter(entry=>path.resolve(base,entry.file||'')===absolute);
    if (relative.startsWith('..') || path.isAbsolute(relative) || matches.length!==1) unverified();
    const entry=matches[0],sha256=hash(fs.readFileSync(absolute));
    if (!/^[a-f0-9]{64}$/.test(entry.exportHash||'') || sha256!==entry.exportHash) unverified();
    return {...entry,sha256,filename:path.basename(absolute),groupIndex:index};
  });
  if (new Set(rows.map(row=>row.filename+'\0'+row.sha256)).size!==rows.length) unverified();
  return rows;
}

function createUploadEvidenceCapture(page, options) {
  return {async run(files, execute) {
    if (activePages.has(page)) fail('UPLOAD_CAPTURE_BUSY','同一页面已有图片证据采集，已阻止并发上传');
    const expected=expectedFiles(options.root,options.delivery,files);
    if (typeof execute!=='function' || typeof page.on!=='function' || typeof page.off!=='function') unverified();
    const assets=new Map(),requests=new Map(),pending=new Set();
    let failure=null,sealed=false;
    function track(promise) {
      pending.add(promise);
      promise.catch(()=>{failure=new EvidenceError('UPLOAD_EVIDENCE_UNVERIFIED','平台上传证据不完整或有歧义，已阻止保存');})
        .finally(()=>pending.delete(promise));
      return promise;
    }
    function onRequest(request) {
      if (sealed || request.method()!=='POST' || !trustedUpload(request.url())) return;
      const record={finished:false,data:null};
      record.parsed=track((async()=>{
        const type=typeof request.headerValue==='function'?await request.headerValue('content-type'):
          Object.entries(request.headers()).find(([key])=>key.toLowerCase()==='content-type')?.[1];
        if (!/^multipart\/form-data\s*;/i.test(type||'')) {record.finished=true;return null;}
        if (request.redirectedFrom?.()) unverified();
        const body=request.postDataBuffer();
        const [file]=await multipartFiles(body,type);
        const matches=expected.filter(row=>row.filename===file.filename && row.sha256===file.sha256);
        if (matches.length!==1) unverified();
        const endpoint=new URL(request.url());
        return record.data={file,entry:matches[0],requestHash:hash(body),
          requestOrigin:endpoint.origin,requestPath:endpoint.pathname};
      })());
      requests.set(request,record);
    }
    function onResponse(response) {
      const record=requests.get(response.request());
      if (!record || sealed) return;
      track((async()=>{
        const input=await record.parsed;
        if (!input) return;
        if (!trustedUpload(response.url()) || response.status()<200 || response.status()>=300) unverified();
        const body=await response.body(),resource=responseResource(body,input.file);
        if (assets.has(input.entry.file) || [...assets.values()].some(row=>row.url===resource.url || row.assetId===resource.assetId)) unverified();
        assets.set(input.entry.file,{file:input.entry.file,slot:input.entry.slot,sha256:input.file.sha256,
          section:input.entry.section,groupValue:options.groupValue ?? null,groupIndex:input.entry.groupIndex,
          filename:input.file.filename,...resource,requestHash:input.requestHash,responseHash:hash(body),
          evidence:{method:'POST',requestOrigin:input.requestOrigin,requestPath:input.requestPath,
            requestHash:input.requestHash,responseHash:hash(body),multipartField:input.file.field,
            fileBodyOffset:input.file.bodyOffset,fileSize:input.file.size,fileSha256:input.file.sha256,
            responseUrlPath:resource.responseUrlPath,responseIdentityPath:resource.responseIdentityPath}});
        record.finished=true;
      })());
    }
    function onFailed(request) {
      const record=requests.get(request);
      if (record) track(record.parsed.then(input=>{if (input) unverified();}));
    }
    activePages.add(page);
    page.on('request',onRequest);page.on('response',onResponse);page.on('requestfailed',onFailed);
    try {
      await execute();
      const deadline=Date.now()+(options.timeoutMs??15000),settle=options.settleMs??200;
      let completeSince=null,settled=false;
      while (Date.now()<=deadline) {
        if (failure) throw failure;
        const complete=assets.size===expected.length && pending.size===0 && [...requests.values()].every(row=>row.finished);
        if (complete) {completeSince??=Date.now();if (Date.now()-completeSince>=settle) {settled=true;break;}}
        else completeSince=null;
        await new Promise(resolve=>setTimeout(resolve,Math.min(20,Math.max(1,deadline-Date.now()))));
      }
      if (failure) throw failure;
      if (assets.size!==expected.length || pending.size || [...requests.values()].some(row=>!row.finished) || !settled) unverified();
      // Recheck source bytes after the upload; changing a reviewed file mid-flight cannot pass.
      expectedFiles(options.root,options.delivery,files);
      return {evidenceVersion:1,source:'observed-multipart-upload',assets:expected.map(row=>assets.get(row.file)),
        capability:{adapterVersion:1,uploadObserved:true,savedSectionsObserved:false,liveVerified:false}};
    } finally {
      sealed=true;
      page.off('request',onRequest);page.off('response',onResponse);page.off('requestfailed',onFailed);
      activePages.delete(page);
    }
  }};
}

// Runs inside page.evaluate. Only fixed vendor selectors and structural ownership are used.
function snapshotImageSections({groupValues,knownGroups,selectors}) {
  function stop() {throw Error('IMAGE_SECTION_DOM_UNVERIFIED');}
  const all=node=>Array.from(node);
  const groupBoxes=node=>all(node.querySelectorAll('input[type="checkbox"][value]'))
    .filter(box=>knownGroups.includes(Number(box.value)));
  const mainInputs=all(document.querySelectorAll(selectors.mainInput));
  if (mainInputs.length!==1) stop();
  let main=mainInputs[0].parentElement;
  while (main && !main.querySelectorAll(selectors.mainItem).length) main=main.parentElement;
  if (!main || groupBoxes(main).length || main.querySelectorAll(selectors.mainInput).length!==1) stop();
  const mainUrls=all(main.querySelectorAll(selectors.mainItem+' img')).map(image=>image.currentSrc||image.getAttribute('src')||'');
  const groups=[],containers=[];
  for (const value of groupValues) {
    const boxes=all(document.querySelectorAll('input[type="checkbox"][value="'+value+'"]'));
    if (boxes.length!==1 || boxes[0].checked!==true) stop();
    let container=boxes[0].parentElement;
    while (container && !container.querySelectorAll(selectors.detailUpload).length) container=container.parentElement;
    if (!container) stop();
    const checkboxes=groupBoxes(container),uploaders=all(container.querySelectorAll(selectors.detailUpload));
    if (checkboxes.length!==1 || checkboxes[0]!==boxes[0] || uploaders.length!==1 ||
        containers.some(old=>old.contains(container)||container.contains(old)) || main.contains(container)||container.contains(main)) stop();
    containers.push(container);
    const uploader=uploaders[0];
    if (uploader.querySelectorAll('input[type="file"]').length!==1) stop();
    const urls=all(uploader.querySelectorAll('img')).map(image=>image.currentSrc||image.getAttribute('src')||'');
    groups.push({value,urls,checkboxChecked:true,containerUnique:true});
  }
  return {main:{urls:mainUrls,containerUnique:true},groups};
}

async function readSavedImageSections(page, options) {
  let url;
  try {url=new URL(page.url());} catch {unverified();}
  const id=String(options.expectedDraftId||'');
  if (!/^[1-9][0-9]{0,24}$/.test(id) || url.protocol!=='https:' || url.hostname!=='post.alibaba.com' ||
      url.username || url.password || url.port && url.port!=='443' || url.pathname!=='/product/publish.htm' ||
      url.searchParams.getAll('itemId').length!==1 || url.searchParams.get('itemId')!==id)
    fail('SAVED_ITEM_UNVERIFIED','当前页面未唯一绑定目标itemId，图片回读已阻止');
  const delivery=options.delivery,uploaded=options.uploaded;
  if (!Array.isArray(delivery) || !delivery.length || !Array.isArray(uploaded) || uploaded.length!==delivery.length ||
      new Set(uploaded.map(row=>row.slot)).size!==delivery.length ||
      new Set(uploaded.map(row=>row.assetId)).size!==delivery.length ||
      new Set(uploaded.map(row=>row.actual||row.url)).size!==delivery.length) unverified();
  for (const entry of delivery) {
    const row=uploaded.find(item=>item.slot===entry.slot);
    if (!row || (row.exportHash||row.sha256)!==entry.exportHash || !row.assetId ||
        !['platform-url','platform-asset-id'].includes(row.identityKind) ||
        !/^[a-f0-9]{64}$/.test(row.requestHash||'') || !/^[a-f0-9]{64}$/.test(row.responseHash||'')) unverified();
    canonicalResourceUrl(row.actual||row.url);
    if (row.identityKind==='platform-url' && row.assetId!==canonicalResourceUrl(row.actual||row.url)) unverified();
  }
  const groupValues=[...new Set(uploaded.filter(row=>row.section!=='main').map(row=>Number(row.groupValue)))];
  if (groupValues.some(value=>!GROUP_VALUES.includes(value))) unverified();
  let snapshot;
  try {snapshot=await page.evaluate(snapshotImageSections,{groupValues,knownGroups:GROUP_VALUES,selectors:SELECTORS});}
  catch {fail('IMAGE_SECTION_DOM_UNVERIFIED','保存后图片分区容器未唯一定位，已阻止登记成功');}
  const actualBySlot=new Map();
  function bind(rows,actualUrls,groupValue) {
    const expected=rows.toSorted((a,b)=>a.groupIndex-b.groupIndex);
    if (!Array.isArray(actualUrls) || actualUrls.length!==expected.length ||
        expected.some((row,index)=>row.groupIndex!==index)) unverified();
    expected.forEach((row,index)=>{
      const actual=canonicalResourceUrl(actualUrls[index]),wanted=canonicalResourceUrl(row.actual||row.url);
      if (actual!==wanted) fail('IMAGE_ORDER_UNVERIFIED','保存后图片URL、分区或顺序与实际上传证据不符');
      actualBySlot.set(row.slot,{assetId:String(row.assetId),url:actual,identityKind:row.identityKind,
        observedIdentityKind:'platform-url',assetIdSource:'upload-response',urlSource:'saved-section-dom',
        groupValue,groupIndex:index,itemId:id});
    });
  }
  bind(uploaded.filter(row=>row.section==='main'),snapshot.main?.urls,null);
  for (const value of groupValues) {
    const group=snapshot.groups?.filter(row=>row.value===value);
    if (group?.length!==1 || group[0].containerUnique!==true || group[0].checkboxChecked!==true) unverified();
    bind(uploaded.filter(row=>Number(row.groupValue)===value && row.section!=='main'),group[0].urls,value);
  }
  const sections={main:[],detail:[],parameters:[]};
  for (const entry of delivery) {
    if (!sections[entry.section] || !actualBySlot.has(entry.slot)) unverified();
    sections[entry.section].push(actualBySlot.get(entry.slot));
  }
  if (page.url()!==url.href) fail('SAVED_ITEM_UNVERIFIED','图片回读期间页面已变化，未登记成功');
  return {evidenceVersion:1,source:'saved-item-section-dom',itemId:id,sections,
    snapshotHash:hash(Buffer.from(JSON.stringify(snapshot))),
    capability:{adapterVersion:1,uploadObserved:true,savedSectionsObserved:true,liveVerified:false}};
}

module.exports={EvidenceError,capability,canonicalResourceUrl,multipartFiles,responseResource,
  verifyUploadReplay,createUploadEvidenceCapture,snapshotImageSections,readSavedImageSections};
