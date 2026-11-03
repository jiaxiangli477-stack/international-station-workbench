const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'workflow.js'), 'utf8');
function run(code) {
  return vm.runInNewContext(source + '\n' + code, {
    localStorage: { getItem: () => null },
    document: { addEventListener() {} },
    URLSearchParams,
  });
}
test('missing facts prevent handoff even if review checkboxes are selected', () => {
  const missing = run(`const p={id:'test',stage:2}; const f=getFlow(p); f.checks[2]={facts:true,scope:true}; flowMissing(p);`);
  assert.equal(missing.length, 3);
});
test('concept visuals can proceed with scope and basic product facts', () => {
  const missing = run(`const p={id:'test',stage:2}; const f=getFlow(p); f.facts={market:'TEST',form:'TEST',spec:'TEST',formula:'',mode:'concept'};f.checks[2]={facts:true,scope:true};flowMissing(p);`);
  assert.equal(missing.length, 0);
});
test('concepts cannot pass listing preparation through checkboxes alone', () => {
  const missing = run(`const p={id:'test',stage:4};const f=getFlow(p);f.facts={market:'TEST',form:'TEST',spec:'TEST',formula:'',mode:'concept'};f.checks[4]={fields:true,commercial:true,assets:true,compliance:true};flowMissing(p);`);
  assert.equal(missing.length, 2);
  assert.ok(missing.some(s => s.includes('配方')));
  assert.ok(missing.some(s => s.includes('概念')));
});
test('listing demo needs both confirmed-mode facts and all review requirements', () => {
  const missing = run(`const p={id:'test',stage:4};const f=getFlow(p);f.facts={market:'TEST',form:'TEST',spec:'TEST',formula:'TEST-REFERENCE',mode:'real'};f.checks[4]={fields:true,commercial:true,assets:true};flowMissing(p);`);
  assert.equal(missing.length, 1);
  assert.ok(missing[0].includes('合规'));
});
test('returning a stage preserves previous approvals but invalidates downstream reviews', () => {
  const result = run(`const f={approvals:{2:{},3:{},4:{}},checks:{2:{facts:true},3:{package:true},4:{fields:true}},completed:true};invalidateFlow(f,3);JSON.stringify(f);`);
  const parsed = JSON.parse(result);
  assert.deepEqual(Object.keys(parsed.approvals), ['2']);
  assert.deepEqual(Object.keys(parsed.checks), ['2']);
  assert.equal(parsed.completed, false);
});
