'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {EventEmitter}=require('node:events');
const adapter=require('../listing_image_evidence.cjs');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const image=name=>Buffer.from([137,80,78,71,13,10,26,10,0,255,0,...Buffer.from(name)]);
const cdn=name=>'https://sc04.alicdn.com/kf/'+name+'.png';

function multipart(parts) {
  const boundary='fixture-upload-boundary';
  const chunks=[Buffer.from('--'+boundary+'\r\nContent-Disposition: form-data; name="auth"\r\n\r\nfixture-private-token\r\n')];
  for (const part of parts) chunks.push(Buffer.from('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+part.name+'"\r\nContent-Type: image/png\r\n\r\n'),part.bytes,Buffer.from('\r\n'));
  chunks.push(Buffer.from('--'+boundary+'--\r\n'));
  return {body:Buffer.concat(chunks),contentType:'multipart/form-data; boundary='+boundary};
}

class FakePage extends EventEmitter {
  constructor(){super();this.currentUrl='https://post.alibaba.com/product/publish.htm?itemId=12345';}
  url(){return this.currentUrl;}
  async evaluate(fn,arg){
    const previous=global.document;
    global.document=this.document;
    try{return fn(arg);}finally{if(previous===undefined)delete global.document;else global.document=previous;}
  }
}

function fixture(t, names=['m1']) {
  const root=fs.mkdtempSync(path.join('D:/Codex','listing-evidence-fixture-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const delivery=names.map(name=>{
    const file=name+'.png',bytes=image(name);fs.writeFileSync(path.join(root,file),bytes);
    return {slot:name,file,section:name.startsWith('m')?'main':'detail',exportHash:hash(bytes)};
  });
  return {root,delivery,files:delivery.map(row=>path.join(root,row.file)),page:new FakePage()};
}

function emitUpload(page,parts,response,options={}) {
  const wire=multipart(parts);
  const request={method:()=>options.method||'POST',url:()=>options.url||'https://kfupload.alibaba.com/upload?token=fixture-private-token',
    headerValue:async name=>name==='content-type'?wire.contentType:null,
    headers:()=>{throw Error('No complete headers should be requested');},postDataBuffer:()=>wire.body};
  const bytes=Buffer.from(JSON.stringify(response));
  page.emit('request',request);
  page.emit('response',{request:()=>request,url:()=>options.responseUrl||request.url(),status:()=>options.status||200,body:async()=>bytes});
  return {requestBody:wire.body,contentType:wire.contentType,responseBody:bytes};
}

function capture(f,options={}) {
  return adapter.createUploadEvidenceCapture(f.page,{root:f.root,delivery:f.delivery,timeoutMs:250,settleMs:0,...options});
}

test('captures binary multipart sha and actual unique URL without inventing a server id',async t=>{
  const f=fixture(t);let wire;
  const result=await capture(f).run(f.files,async()=>{
    wire=emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],{success:true,data:{id:'not-a-verified-asset-id',url:cdn('m1')}});
  });
  const row=result.assets[0];
  assert.equal(row.sha256,f.delivery[0].exportHash);
  assert.equal(row.identityKind,'platform-url');assert.equal(row.assetId,cdn('m1'));
  assert.equal(row.requestHash,hash(wire.requestBody));assert.equal(row.responseHash,hash(wire.responseBody));
  assert.equal(row.evidence.fileSize,image('m1').length);
  assert.equal(await adapter.verifyUploadReplay(row,wire),true);
  assert.equal(JSON.stringify(result).includes('fixture-private-token'),false);
  assert.equal(f.page.listenerCount('response'),0);assert.equal(f.page.listenerCount('request'),0);
});

test('only explicit response assetId or imageId can provide a server identity',async t=>{
  const f=fixture(t);
  const result=await capture(f).run(f.files,async()=>emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],
    {success:true,data:{assetId:'7654321',imageUrl:cdn('m1')}}));
  assert.equal(result.assets[0].assetId,'7654321');assert.equal(result.assets[0].identityKind,'platform-asset-id');
  assert.deepEqual(result.assets[0].responseIdentityPath,['data','assetId']);
});

test('wrong file bytes or echoed file hash cannot pass',async t=>{
  for(const kind of ['request-bytes','response-hash']){
    const f=fixture(t);
    await assert.rejects(capture(f).run(f.files,async()=>emitUpload(f.page,
      [{name:'m1.png',bytes:image(kind==='request-bytes'?'different':'m1')}],
      {success:true,data:{url:cdn('m1'),...(kind==='response-hash'?{sha256:'0'.repeat(64)}:{})}})),
      error=>error.code==='UPLOAD_EVIDENCE_UNVERIFIED');
  }
});

test('multiple response resources and unverified multi-file batch association are rejected',async t=>{
  const f=fixture(t,['m1','m2']);
  await assert.rejects(capture(f).run(f.files,async()=>emitUpload(f.page,
    [{name:'m1.png',bytes:image('m1')},{name:'m2.png',bytes:image('m2')}],
    {success:true,data:[{url:cdn('m1')},{url:cdn('m2')}]})));
  const one=fixture(t);
  await assert.rejects(capture(one).run(one.files,async()=>emitUpload(one.page,
    [{name:'m1.png',bytes:image('m1')}],{success:true,data:[{url:cdn('m1')},{url:cdn('other')}]})));
});

test('success false, id-only responses and foreign or signed resource URLs are rejected',async t=>{
  const responses=[{success:false,data:{url:cdn('m1')}},{success:true,data:{id:'123'}},
    {success:true,data:{url:'https://evil.example/image.png'}},
    {success:true,data:{url:cdn('m1')+'?token=fixture-private-token'}},
    {code:200,data:{url:cdn('m1')}}];
  for(const response of responses){
    const f=fixture(t);
    await assert.rejects(capture(f).run(f.files,async()=>emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],response)));
  }
});

test('foreign upload origin never supplies evidence even with an Alibaba resource URL',async t=>{
  const f=fixture(t);
  await assert.rejects(capture(f,{timeoutMs:30}).run(f.files,async()=>emitUpload(f.page,
    [{name:'m1.png',bytes:image('m1')}],{success:true,data:{url:cdn('m1')}},{url:'https://evil.example/upload'})));
});

test('duplicate successful requests for the same file cannot silently replace its resource',async t=>{
  const f=fixture(t);
  await assert.rejects(capture(f).run(f.files,async()=>{
    emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],{success:true,data:{url:cdn('m1')}});
    emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],{success:true,data:{url:cdn('duplicate')}});
  }));
});

test('replay rejects an altered raw response even if its resource URL is unchanged',async t=>{
  const f=fixture(t);let wire;
  const result=await capture(f).run(f.files,async()=>{wire=emitUpload(f.page,
    [{name:'m1.png',bytes:image('m1')}],{success:true,data:{url:cdn('m1')}});});
  await assert.rejects(adapter.verifyUploadReplay(result.assets[0],{...wire,responseBody:Buffer.concat([wire.responseBody,Buffer.from('\n')])}));
});

class Element {
  constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.value=attrs.value;this.checked=attrs.checked===true;
    this.currentSrc=attrs.src||'';this.children=children;for(const child of children)child.parentElement=this;}
  getAttribute(name){return this.attrs[name]??null;}
  contains(other){return this===other || this.children.some(child=>child.contains(other));}
  matches(selector){
    const tag=selector.match(/^[a-z]+/i)?.[0];if(tag && tag!==this.tag)return false;
    for(const match of selector.matchAll(/\.([\w-]+)/g))if(!(this.attrs.class||'').split(' ').includes(match[1]))return false;
    for(const match of selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)){
      if(!(match[1] in this.attrs) || match[2]!==undefined && String(this.attrs[match[1]])!==match[2])return false;
    }
    return true;
  }
  querySelectorAll(selector){
    const parts=selector.split(' '),last=parts.pop(),descendants=[];
    const walk=node=>{for(const child of node.children){descendants.push(child);walk(child);}};walk(this);
    return descendants.filter(node=>{
      if(!node.matches(last))return false;let parent=node.parentElement;
      for(let index=parts.length-1;index>=0;index--){while(parent && !parent.matches(parts[index]))parent=parent.parentElement;
        if(!parent)return false;parent=parent.parentElement;}
      return true;
    });
  }
}
const el=(tag,attrs,children)=>new Element(tag,attrs,children);
function dom({main=[cdn('m1')],groups=[{value:200,urls:[cdn('d1')]}],extraMain=false,ambiguous=false}={}){
  const mainRoot=el('section',{},[el('div',{class:'upload-select-inner'},[el('input',{type:'file'})]),
    ...main.map(src=>el('div',{class:'image-upload-list-item'},[el('img',{src})]))]);
  const groupRoots=groups.map(group=>el('section',{},[
    el('label',{},[el('input',{type:'checkbox',value:String(group.value),checked:true})]),
    el('div',{class:'next-upload upload-image'},[el('input',{type:'file'}),...group.urls.map(src=>el('img',{src}))])
  ]));
  if(ambiguous)groupRoots[0].children.push(el('div',{class:'next-upload upload-image'},[el('input',{type:'file'})]));
  return el('document',{},[mainRoot,...groupRoots,...(extraMain?[el('div',{class:'upload-select-inner'},[el('input',{type:'file'})])]:[])]);
}

async function observedPair(t){
  const f=fixture(t,['m1','d1']);
  const main=await capture(f).run([f.files[0]],async()=>emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],
    {success:true,data:{url:cdn('m1')}}));
  const detail=await capture(f,{groupValue:200}).run([f.files[1]],async()=>emitUpload(f.page,[{name:'d1.png',bytes:image('d1')}],
    {success:true,data:{imageId:'900',url:cdn('d1')}}));
  f.uploaded=[...main.assets,...detail.assets];f.page.document=dom();
  f.options={expectedDraftId:'12345',delivery:f.delivery,uploaded:f.uploaded};
  return f;
}

test('saved item DOM uniquely binds main and checkbox-owned detail images to observed resources',async t=>{
  const f=await observedPair(t),result=await adapter.readSavedImageSections(f.page,f.options);
  assert.equal(result.sections.main[0].assetId,cdn('m1'));
  assert.equal(result.sections.detail[0].assetId,'900');
  assert.equal(result.sections.detail[0].observedIdentityKind,'platform-url');
  assert.equal(result.sections.detail[0].groupValue,200);assert.equal(result.sections.detail[0].groupIndex,0);
  assert.match(result.snapshotHash,/^[a-f0-9]{64}$/);
  assert.equal(result.capability.liveVerified,false);
});

test('wrong or duplicate itemId and an untrusted editor URL block readback before DOM access',async t=>{
  const f=await observedPair(t);
  for(const value of ['https://post.alibaba.com/product/publish.htm?itemId=999',
    'https://post.alibaba.com/product/publish.htm?itemId=12345&itemId=12345',
    'https://post.alibaba.com.evil.example/product/publish.htm?itemId=12345']){
    f.page.currentUrl=value;
    await assert.rejects(adapter.readSavedImageSections(f.page,f.options),error=>error.code==='SAVED_ITEM_UNVERIFIED');
  }
});

test('ambiguous section containers or main upload inputs cannot be replaced by global last()',async t=>{
  const f=await observedPair(t);
  for(const document of [dom({ambiguous:true}),dom({extraMain:true})]){
    f.page.document=document;
    await assert.rejects(adapter.readSavedImageSections(f.page,f.options),error=>error.code==='IMAGE_SECTION_DOM_UNVERIFIED');
  }
});

test('URL in the wrong section cannot be accepted from a page-global image search',async t=>{
  const f=await observedPair(t);
  f.page.document=dom({main:[cdn('d1')],groups:[{value:200,urls:[cdn('m1')]}]});
  await assert.rejects(adapter.readSavedImageSections(f.page,f.options),error=>error.code==='IMAGE_ORDER_UNVERIFIED');
});

test('two images in a detail group must keep their actual upload order',async t=>{
  const f=fixture(t,['m1','d2','d3']);
  const main=await capture(f).run([f.files[0]],async()=>emitUpload(f.page,[{name:'m1.png',bytes:image('m1')}],{success:true,data:{url:cdn('m1')}}));
  const details=await capture(f,{groupValue:110}).run(f.files.slice(1),async()=>{
    // Network completion order differs from file order; response identity remains request-bound.
    emitUpload(f.page,[{name:'d3.png',bytes:image('d3')}],{success:true,data:{url:cdn('d3')}});
    emitUpload(f.page,[{name:'d2.png',bytes:image('d2')}],{success:true,data:{url:cdn('d2')}});
  });
  f.page.document=dom({groups:[{value:110,urls:[cdn('d2'),cdn('d3')]}]});
  const options={expectedDraftId:'12345',delivery:f.delivery,uploaded:[...main.assets,...details.assets]};
  assert.equal((await adapter.readSavedImageSections(f.page,options)).sections.detail[1].groupIndex,1);
  f.page.document=dom({groups:[{value:110,urls:[cdn('d3'),cdn('d2')]}]});
  await assert.rejects(adapter.readSavedImageSections(f.page,options),error=>error.code==='IMAGE_ORDER_UNVERIFIED');
});

test('unknown live capability remains explicitly unaccepted',()=>{
  const support=adapter.capability();
  assert.equal(support.implemented,true);assert.equal(support.canAttemptCapture,true);
  assert.equal(support.ready,false);assert.equal(support.liveVerified,false);
});
