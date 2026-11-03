const test=require('node:test'); const assert=require('node:assert/strict');
const {bindUploadEvidence, verifyImageEvidence}=require('../listing_runner.cjs');
const delivery=[{slot:'m1',file:'a.png',section:'main',exportHash:'hash-a'}, {slot:'m2',file:'b.png',section:'main',exportHash:'hash-b'}, {slot:'m7',file:'c.png',section:'parameters',exportHash:'hash-c'}, {slot:'d1',file:'d.png',section:'detail',exportHash:'hash-d'}];
const assets=delivery.map((r,i)=>({file:r.file,sha256:r.exportHash,assetId:'asset-'+i,url:'https://cdn.test/'+i}));
test('upload binds by verified file and hash even when response order is reversed',()=>{
 const rows=bindUploadEvidence('D:/fixture',delivery,delivery.map(r=>'D:/fixture/'+r.file),{evidenceVersion:1,assets:[...assets].reverse()});
 assert.deepEqual(rows.map(r=>r.assetId),assets.map(r=>r.assetId));
});
test('URL-count-only evidence and wrong file hash cannot prove uploads',()=>{
 assert.throws(()=>bindUploadEvidence('D:/fixture',delivery,['D:/fixture/a.png'],{urls:['https://cdn.test/0']}));
 assert.throws(()=>bindUploadEvidence('D:/fixture',delivery,['D:/fixture/a.png'],{evidenceVersion:1,assets:[{...assets[0],sha256:'wrong'}]}));
});
test('saved sections and order must match file-bound asset identities',()=>{
 const rows=bindUploadEvidence('D:/fixture',delivery,delivery.map(r=>'D:/fixture/'+r.file),{evidenceVersion:1,assets});
 const good={evidenceVersion:1,sections:{main:assets.slice(0,2),parameters:[assets[2]],detail:[assets[3]]}};
 assert.ok(verifyImageEvidence(delivery,rows,good).every(r=>r.matched));
 for(const sections of [{...good.sections,main:[assets[1],assets[0]]},{...good.sections,parameters:[],detail:[assets[2],assets[3]]},{...good.sections,main:[assets[3],assets[1]],detail:[assets[0]]},{main:[{assetId:'unrelated'},{assetId:'other'}],parameters:[],detail:[]}]) {
   assert.ok(verifyImageEvidence(delivery,rows,{evidenceVersion:1,sections}).some(r=>!r.matched));
 }
 assert.ok(verifyImageEvidence(delivery,rows,{}).every(r=>!r.matched));
});
