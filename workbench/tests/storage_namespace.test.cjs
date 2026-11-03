const {test}=require('node:test');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const vm=require('node:vm');
const path=require('node:path');
const generated=spawnSync('python',['-c',"import json,serve; print(json.dumps({k:serve.storage_namespace_script(k) for k in ['a','b']}))"],{cwd:path.join(__dirname,'..'),encoding:'utf8'});
assert.equal(generated.status,0,generated.stderr);
const scripts=JSON.parse(generated.stdout);
const backing=new Map();
const setup=`class Storage {
get length(){return backing.size}
key(i){return [...backing.keys()][i]||null}
getItem(k){return backing.get(String(k))??null}
setItem(k,v){backing.set(String(k),String(v))}
removeItem(k){backing.delete(String(k))}
clear(){backing.clear()}}
var localStorage=new Storage();var window={localStorage};`;
function frame(name){const context=vm.createContext({backing});vm.runInContext(setup,context);if(name)vm.runInContext(scripts[name].replace('<script>','').replace('</script>',''),context);return code=>vm.runInContext(code,context)}
test('store A, store B and parent workspace storage do not overwrite each other',()=>{
  const parent=frame(),a=frame('a'),b=frame('b');
  parent("localStorage.setItem('note','parent')");
  a("localStorage.setItem('note','A')");b("localStorage.setItem('note','B')");
  assert.equal(a("localStorage.getItem('note')"),'A');
  assert.equal(b("localStorage.getItem('note')"),'B');
  assert.equal(parent("localStorage.getItem('note')"),'parent');
  assert.equal(a('localStorage.length'),1);
  assert.equal(a('localStorage.key(0)'),'note');
  a('localStorage.clear()');
  assert.equal(a('localStorage.length'),0);
  assert.equal(b("localStorage.getItem('note')"),'B');
  assert.equal(parent("localStorage.getItem('note')"),'parent');
});
