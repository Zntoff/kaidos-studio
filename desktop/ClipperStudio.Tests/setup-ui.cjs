// Exercise the first-run actions without a WebView or real API key.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const elements = new Map(), calls = [];
let html = '', rejectKey = false, closed = false;
const element = selector => {
  if (!elements.has(selector)) elements.set(selector, { value: '', style: {}, textContent: '', innerHTML: '', setAttribute() {} });
  return elements.get(selector);
};
const ctx = vm.createContext({
  cfg: { desktop: true, output_dir: 'C:\\Videos', setup_completed: false, api_key_set: false, ffmpeg: false },
  $: element, esc: s => String(s).replaceAll('&', '&amp;').replaceAll('"', '&quot;'),
  modal: content => { html = content; closed = false; elements.clear(); },
  closeModal: () => { closed = true; }, toast: () => {},
  send: async (method, url, body) => {
    calls.push({ method, url, body });
    if (url.endsWith('/ai/key') && rejectKey) throw new Error('Key rechazada');
    if (url.endsWith('/ai/key')) ctx.cfg.api_key_set = true;
    if (body.completed) ctx.cfg.setup_completed = true;
    if (body.output_dir) ctx.cfg.output_dir = body.output_dir;
    return {};
  },
  api: async () => ctx.cfg,
  post: async () => ({ path: 'D:\\Clips' }),
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../clipper/web/static/settings.js'), 'utf8'), ctx);
(async () => {
  ctx.desktopSetup();
  assert.match(html, /Paso 1 de 2/);
  await element('#setupBrowse').onclick();
  assert.equal(element('#setupPath').value, 'D:\\Clips');
  await element('#setupNext').onclick();
  assert.match(html, /Paso 2 de 2/);
  assert.equal(ctx.cfg.setup_completed, false);
  await element('#setupSkipKey').onclick();
  assert.equal(ctx.cfg.setup_completed, true);
  assert.equal(calls.some(c => c.url.endsWith('/ai/key')), false);
  assert.equal(closed, true);

  ctx.cfg.setup_completed = false;
  ctx.desktopSetup();
  await element('#setupLater').onclick();
  assert.equal(ctx.cfg.setup_completed, true);

  ctx.cfg.setup_completed = false;
  ctx.desktopSetup();
  element('#setupSkip').onclick();
  const previousCalls = calls.length;
  await element('#setupSaveKey').onclick();
  assert.equal(calls.length, previousCalls);
  assert.match(element('#setupError').textContent, /Pega tu API key/);
  element('#setupKey').value = 'test-key';
  rejectKey = true;
  await element('#setupSaveKey').onclick();
  assert.equal(ctx.cfg.setup_completed, false);
  assert.equal(element('#setupError').textContent, 'Key rechazada');
  assert.equal(element('#setupSaveKey').disabled, false);
  rejectKey = false;
  await element('#setupSaveKey').onclick();
  assert.equal(ctx.cfg.setup_completed, true);
  assert.equal(ctx.cfg.api_key_set, true);
  assert.equal(closed, true);
  console.log('Passed desktop setup UI flows (folder, save, skip, validation and retry).');
})().catch(error => { console.error(error); process.exitCode = 1; });
