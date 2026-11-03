const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
test('inquiry revision replaces same-period edition while retaining stores, types and history', () => {
  const context = vm.createContext({document:{addEventListener(){}},integrationRegistry:{shared:{records:[]}}});
  vm.runInContext(fs.readFileSync('share.js','utf8'),context);
  const row=(id,reportType='inquiry',start='2026-10-08',versionTime='2026-10-16T14:34:37',complete=true)=>({id,store:'lifeworthcn',kind:'inquiry',reportType,start,end:'2026-10-15',periodEnd:'2026-10-15',versionTime,complete});
  context.integrationRegistry.shared.records=[row('old','inquiry',undefined,'2026-10-16T12:00:00'),row('new'),row('ledger','customer_ledger'),row('history','inquiry','2026-10-01'),{...row('other-store'),store:'youhealth'},row('broken','inquiry',undefined,'2026-10-17T00:00:00',false)];
  const ids=Array.from(vm.runInContext("sharedRecords('inquiry','lifeworthcn').map(r=>r.id)",context));
  assert.deepEqual(ids.sort(),['history','ledger','new']);
});
