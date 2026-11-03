const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const app = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const integrations = fs.readFileSync(path.join(__dirname, '..', 'integrations.js'), 'utf8');
const executionUI = fs.readFileSync(path.join(__dirname, '..', 'execution_ui.js'), 'utf8');

test('Skill Center names the actual approved workbench skills', () => {
  for (const name of ['alibaba-growth-os-share', 'alibaba-inquiry-dossier', 'b2b-image-skill', 'alibaba-attribute-filler']) {
    assert.ok(app.includes(name), `missing approved skill mapping: ${name}`);
  }
});

test('Skill Center shows a distinct integration state for each entry', () => {
  assert.ok(app.includes('statusLabel'));
  assert.ok(app.includes('未接入'));
  assert.ok(app.includes('部分接入'));
});

test('Skill Center summary count matches the current six partially integrated entries', () => {
  assert.ok(app.includes('当前 6 项部分接入、0 项未接入'));
});

test('product intelligence Skill detail opens the connected manifest-only diagnostic flow', () => {
  assert.ok(app.includes("['selection','images','listing','inquiries','quality','analytics']"));
  assert.ok(executionUI.includes("id==='quality'"));
  assert.ok(executionUI.includes('manifest_only'));
});

test('analytics Skill detail distinguishes weekly execution from the readonly report page', () => {
  assert.ok(app.includes("'quality','analytics']"));
  assert.ok(executionUI.includes("id==='analytics'"));
  assert.ok(executionUI.includes('collectionEnabled=false'));
});

test('Skill Center no longer claims every candidate is disconnected', () => {
  assert.ok(!app.includes('均未连接执行引擎'));
  assert.ok(!app.includes('6 项能力待接入 · 0 项已连接'));
});

test('Applications list does not describe all existing pages as a UI preview', () => {
  assert.ok(!app.includes('当前为可交互界面预览'));
  assert.ok(!app.includes('功能待接入'));
});

test('global header gives Skill Center its real integration status', () => {
  assert.ok(integrations.includes("current==='skills'"));
  assert.ok(integrations.includes('Skill 接入状态'));
});

test('integration report distinguishes report viewing from inquiry task execution', () => {
  assert.ok(!integrations.includes('采集执行尚未接入'));
  assert.ok(integrations.includes('任务链已接入'));
  assert.ok(integrations.includes('本页只读'));
});
