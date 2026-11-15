// Renders the README graphics from source.html with a headless Chromium browser (Edge or Chrome).
//   node docs/readme/render.mjs                         every graphic, dark and light
//   node docs/readme/render.mjs shot raw.png "Title" out.png    frame an app screenshot
// Set BROWSER to the browser executable if it isn't found automatically. Needs Node 22+.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const browser = process.env.BROWSER || [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find(existsSync);
if (!browser) throw new Error('No Chromium browser found; set BROWSER.');

const sleep = ms => new Promise(r => setTimeout(r, ms));
const port = 9400 + Math.floor(Math.random() * 400);
const proc = spawn(browser, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'kreadme-'))}`,
  '--allow-file-access-from-files', '--hide-scrollbars', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
let ws, opened, id = 0; const pending = new Map();
for (let i = 0; i < 60 && !ws; i++) {
  try {
    const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page');
    if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); opened = new Promise(r => ws.onopen = r); }
  } catch {}
  if (!ws) await sleep(250);
}
await opened;
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 1000, deviceScaleFactor: 2, mobile: false });
await send('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });

async function render(hash, out) {
  await send('Page.navigate', { url: pathToFileURL(join(here, 'source.html')).href + '#' + hash });
  await send('Page.reload', { ignoreCache: true });
  await sleep(1200);
  await send('Runtime.evaluate', { expression: 'document.fonts.ready.then(()=>Promise.all([...document.images].map(i=>i.decode().catch(()=>0))))', awaitPromise: true });
  const box = (await send('Runtime.evaluate', { expression: 'JSON.stringify(document.querySelector(".view.on").getBoundingClientRect())', returnByValue: true })).result.value;
  const { x, y, width, height } = JSON.parse(box);
  const shot = await send('Page.captureScreenshot', { format: 'png', clip: { x, y, width, height, scale: 1 }, captureBeyondViewport: true });
  writeFileSync(out, Buffer.from(shot.data, 'base64'));
  console.log('wrote', out);
}

const [mode, ...args] = process.argv.slice(2);
if (mode === 'shot') {
  const [raw, title, out] = args;
  await render(`shot/dark/${encodeURIComponent(pathToFileURL(resolve(raw)).href)}/${encodeURIComponent(title)}`, resolve(out));
} else {
  for (const view of ['banner', 'steps', 'installer', 'portable', 'docker'])
    for (const theme of ['dark', 'light'])
      await render(`${view}/${theme}`, join(here, `${view}-${theme}.png`));
}
ws.close(); proc.kill(); process.exit(0);
