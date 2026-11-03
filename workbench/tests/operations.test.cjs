const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'operations.js'), 'utf8');
function run(code, product = null) {
  return vm.runInNewContext(source + '\n' + code, {
    localStorage: { getItem: () => null }, document: { addEventListener() {} },
    contextProduct: () => product, products: [],
  });
}
test('period aggregation uses the selected daily window', () => {
  assert.deepEqual(JSON.parse(run('JSON.stringify(analyticsTotals(7))')), { exposure: 49300, click: 1035, inquiry: 34 });
  assert.deepEqual(JSON.parse(run('JSON.stringify(analyticsTotals(14))')), { exposure: 88200, click: 1782, inquiry: 55 });
});
test('grade, owner and channel filters compose rather than overwrite each other', () => {
  const ids = run(`buyerGrade='A';buyerOwner='我';buyerChannel='产品询盘';JSON.stringify(filteredBuyers().map(b=>b.id));`);
  assert.deepEqual(JSON.parse(ids), ['BUYER-DEMO-03']);
});
test('product context limits inquiry results to the linked product', () => {
  const ids = run('JSON.stringify(filteredBuyers().map(b=>b.id));', { id: 'DEMO-002' });
  assert.deepEqual(JSON.parse(ids), ['BUYER-DEMO-02']);
});
test('seven-day inquiry view excludes older sample records', () => {
  assert.equal(run('inquiryDays=7;filteredBuyers().length;'), 4);
});
