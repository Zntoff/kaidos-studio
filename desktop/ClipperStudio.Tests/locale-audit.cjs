// Audit the rendered UI in the isolated fixture. No generation, downloads or user-library access.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path');
const assert=require('node:assert/strict');
const neutral=new Set(require('../../clipper/web/static/locales-neutral.json').terms);
const neutralText=s=>neutral.has(s)||/^https?:\/\//.test(s)||/^[\d.,\s:x×%+–−·\/-]+(?:s|fps|LUFS)?$/.test(s)||/^[a-z0-9.-]+\.(?:com|ai|dev|org)$/.test(s)||/^sk-ant-…$/.test(s)||/^♪ [a-z_0-9]+$/.test(s);
const base=process.env.CLIPPER_QA_URL||'http://127.0.0.1:18765';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),report={};
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await require('./session.cjs')(page,base);
  await page.route('**/api/config',async route=>{const response=await route.fetch(),cfg=await response.json();cfg.desktop=true;cfg.setup_completed=true;await route.fulfill({json:cfg});});
  await page.route('**/api/tools',route=>route.fulfill({json:{ffmpeg:{ok:true,version:'FFmpeg'},ytdlp:{ok:false},whisper:{ok:false},gpu:{hardware:false,adapters:[]},dir:'C:/Tools'}}));
  await page.route('**/api/settings/ui-language',route=>route.fulfill({json:{language:JSON.parse(route.request().postData()).language}}));
  let locale;
  const capture=async name=>{await page.evaluate(()=>{I18n.apply?.();return I18n.ready});const missing=(await page.evaluate(()=>I18n.inspect())).filter(s=>!neutralText(s));report[locale+'/'+name]=missing;assert.deepEqual(missing,[],locale+'/'+name+' has untranslated copy');};
  await page.goto(base+'/#/dashboard');await page.evaluate(()=>I18n.ready);
  // Exercise repeated switches in one DOM: translations must always use the original copy.
  for(locale of ['en','pt','fr','de','es']){
  await page.evaluate(l=>I18n.set(l),locale);
  for(const view of ['dashboard','projects','videos','resources','jobs','clips','queue','settings','apis']){
   await page.goto(base+'/#/'+view);await page.locator('#main .page').waitFor();
   await page.waitForFunction(()=>!document.querySelector('#main[aria-busy]'));
   await capture(view);
   if(view==='videos'){
    const expected={en:['Move','Create clip','Process'],es:['Mover','Crear clip','Procesar'],pt:['Mover','Criar clipe','Processar'],fr:['Déplacer','Créer un clip','Traiter'],de:['Verschieben','Clip erstellen','Verarbeiten']}[locale];
    for(const label of expected)assert.ok(await page.getByRole('button',{name:label,exact:true}).count(),locale+': '+label);
    assert.deepEqual(await page.locator('select[name=rights]').first().locator('option').evaluateAll(options=>options.map(o=>o.value)),['own','written_permission','official_press','cc_licensed']);
   }
   if(view==='apis')for(const provider of ['anthropic','openai','gemini','openrouter','mistral','deepseek','groq','ollama','custom']){
    await page.locator('#aiProvider').selectOption(provider);await page.locator(`#aiCard[data-provider=${provider}]`).waitFor();await capture('provider-'+provider);
   }
  }
  const sources=await(await page.request.get(base+'/api/sources')).json(),clips=await(await page.request.get(base+'/api/clips')).json(),jobs=await(await page.request.get(base+'/api/jobs')).json();
  await page.evaluate(id=>newClip(id,24),sources[0].id);await capture('manual-clip');await page.evaluate(closeModal=>window.closeModal(),null);
  await page.evaluate(()=>editProject());await capture('project-dialog');await page.evaluate(()=>closeModal());
  await page.evaluate(id=>moveSource(id),sources[0].id);await capture('move-dialog');await page.evaluate(()=>closeModal());
  await page.evaluate(id=>clip(id),clips[0].id);await capture('preview');await page.evaluate(()=>closeModal());
  await page.evaluate(id=>creativeDialog(id),clips[0].id);await capture('creative-dialog');await page.evaluate(()=>closeModal());
  await page.goto(base+'/#/select/'+jobs[0].id);await page.locator('#cands').waitFor();await capture('selection');
  const checkbox=page.locator('#cands input:not([disabled])').first();if(await checkbox.count()){await checkbox.check();await capture('selection-picked');}
  await page.goto(base+'/#/editor/'+clips[0].id);await page.locator('#edTabs').waitFor();
  for(const tab of ['captions','text','fx','color','audio','format']){
   await page.locator(`#edTabs [data-tab=${tab}]`).click();await capture('editor-'+tab);
  }
  await page.locator('#edTabs [data-tab=text]').click();await page.locator('[data-preset=title]').click();await capture('text-inspector');
  await page.locator('#edTop [data-a=undo]').click();
  await page.evaluate(()=>{Editor.close();desktopSetup(0)});await capture('setup-folder');await page.evaluate(()=>desktopSetup(1));await capture('setup-key');await page.evaluate(()=>closeModal());
  await page.request.delete(base+'/api/clips/'+clips[0].id+'/draft');
  }
  await page.evaluate(()=>{
   const host=document.createElement('div');host.innerHTML='<span data-ui-content>Procesar</span><span class="ttl">Mover</span><input value="Crear clip"><time data-ui-date="2026-11-15T12:30:00Z"></time>';host.id='locale-contract';document.body.append(host);
  });
  for(locale of ['en','de','pt','es','fr','en']){
   await page.evaluate(l=>I18n.set(l),locale);
   assert.equal(await page.locator('#locale-contract [data-ui-content]').innerText(),'Procesar');
   assert.equal(await page.locator('#locale-contract .ttl').innerText(),'Mover');
   assert.equal(await page.locator('#locale-contract input').inputValue(),'Crear clip');
   assert.equal(await page.locator('#locale-contract time').innerText(),await page.evaluate(()=>I18n.date('2026-11-15T12:30:00Z')));
  }
  // Every exact catalog alias must resolve in all five locales, including English originals.
  const exact=await page.evaluate(async()=>{
   const rows=(await(await fetch('/static/locales.tsv')).text()).trim().split(/\r?\n/).map(l=>l.split('\t')),keys=new Map();
   const norm=s=>s.normalize('NFC').replace(/\s+/g,' ').replace(/\u2212/g,'-').trim();
   rows.forEach(row=>{keys.set(norm(row[0]),row);keys.set(norm(row[1]),row)});
   const errors=[];for(const [i,l]of ['es','en','pt','fr','de'].entries()){I18n.set(l);for(const [key,row]of keys)if(I18n.t(key)!==row[i].trim())errors.push(key+': '+l);}
   return errors;
  });assert.deepEqual(exact,[]);assert.deepEqual(errors,[]);
  const output=path.join(process.env.TEMP,'kairos-locale-audit.json');fs.writeFileSync(output,JSON.stringify(report,null,2));
  console.log(`Passed ${Object.keys(report).length} localized views/dialogs/editor tabs/provider panels, all catalog aliases, stable form values, protected video content and locale dates in five languages. Report: ${output}`);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
