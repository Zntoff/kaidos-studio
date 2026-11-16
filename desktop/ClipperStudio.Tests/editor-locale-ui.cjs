// Real drag/save/reload against a synthetic fixture. Localization must never edit video content.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const base=process.env.CLIPPER_QA_URL||'http://127.0.0.1:18765';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1536,height:1000}}),errors=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)});
  await require('./session.cjs')(page,base);
  await page.goto(base+'/#/dashboard');await page.evaluate(()=>I18n.ready);
  await page.getByRole('heading',{name:'What would you like to do today?',exact:true}).waitFor();
  assert.equal(await page.locator('html').getAttribute('lang'),'en');
  const clips=await(await page.request.get(base+'/api/clips')).json();const clip=clips.find(c=>c.edl&&['needs_human','approved','pending_approval'].includes(c.status));
  const before=await(await page.request.get(base+'/api/clips/'+clip.id+'/editor')).json();
  const heading={en:'What would you like to do today?',es:'¿Qué quieres hacer hoy?',pt:'O que você quer fazer hoje?',fr:'Que souhaitez-vous faire aujourd’hui ?',de:'Was möchtest du heute tun?'};
  for(const [locale,title]of Object.entries(heading)){
   await page.locator('#uiLanguageQuick').selectOption(locale);
   await page.getByRole('heading',{name:title,exact:true}).waitFor();
   assert.equal(await page.evaluate(()=>I18n.locale),locale);
   await page.reload();await page.evaluate(()=>I18n.ready);
   await page.getByRole('heading',{name:title,exact:true}).waitFor();
  }
  const unchanged=await(await page.request.get(base+'/api/clips/'+clip.id+'/editor')).json();
  assert.deepEqual(unchanged.edl,before.edl);assert.deepEqual(unchanged.tracks,before.tracks);
  await page.locator('#uiLanguageQuick').selectOption('en');
  await page.goto(base+'/#/editor/'+clip.id);await page.locator('#edHook').waitFor();
  await page.waitForFunction(()=>document.querySelector('#edHook').textContent.length>0);
  assert.equal(await page.locator('#edHook').innerText(),before.edl.hook.text[before.edl.languages[0]].toUpperCase());
  const initial=await page.locator('#edHook').boundingBox();
  const saving=page.waitForResponse(r=>r.url().endsWith('/draft')&&r.request().method()==='PUT');
  await page.mouse.move(initial.x+initial.width/2,initial.y+initial.height/2);await page.mouse.down();
  await page.mouse.move(initial.x+initial.width/2+12,initial.y+initial.height/2+65,{steps:12});await page.mouse.up();await saving;
  const moved=await page.locator('#edHook').boundingBox();assert.ok(moved.y>initial.y+30,'Hook must visibly move');
  const saved=await(await page.request.get(base+'/api/clips/'+clip.id+'/editor')).json();
  assert.ok(saved.edl.hook.y>0&&saved.has_draft);assert.deepEqual(saved.edl.hook.text,before.edl.hook.text);
  await page.reload();await page.locator('#edHook').waitFor();
  const reloaded=await page.locator('#edHook').boundingBox();assert.ok(Math.abs(reloaded.y-moved.y)<3,'Saved hook position must survive reload');
  for(const kind of ['note','cue','text']){
   const edl=structuredClone(before.edl),language=edl.languages[0];
   edl.hook.duration=0;edl.commentary.notes=[];edl.texts=[];
   const tracks=Object.fromEntries(edl.languages.map(l=>[l,{cues:[],word_timed:false}]));
   if(kind==='note')edl.commentary.notes=[{t:0,duration:3,text:{[language]:'Trabajos'},x:.5,y:.4}];
   if(kind==='cue'){edl.captions.x=.5;edl.captions.y=.4;tracks[language].cues=[{start:0,end:3,words:[{w:'Trabajos',start:0,end:3,hl:false}]}];}
   if(kind==='text')edl.texts=[{t:0,duration:3,text:{[language]:'Trabajos'},x:.5,y:.4,font:'caption',size:60,anim_in:'none',anim_out:'none'}];
   const response=await page.request.put(base+'/api/clips/'+clip.id+'/draft',{data:{edl,tracks}});assert.equal(response.status(),200,await response.text());
   await page.reload();const selector=kind==='note'?'#edNote':kind==='cue'?'#edCap':'#edTexts .ed-txt';
   await page.locator(selector).waitFor();const old=await page.locator(selector).boundingBox();
   assert.match(await page.locator(selector).innerText(),/TRABAJOS|Trabajos/,'Video text must remain Spanish in the English interface');
   const done=page.waitForResponse(r=>r.url().endsWith('/draft')&&r.request().method()==='PUT');
   await page.mouse.move(old.x+old.width/2,old.y+old.height/2);await page.mouse.down();
   await page.mouse.move(old.x+old.width/2+5,old.y+old.height/2+30,{steps:8});await page.mouse.up();await done;
   const next=await page.locator(selector).boundingBox();assert.ok(next.y>old.y+15,`${kind} must move`);
   const undo=page.waitForResponse(r=>r.url().endsWith('/draft')&&r.request().method()==='PUT');
   await page.locator('#edTop [data-a=undo]').click();await undo;
   assert.ok(Math.abs((await page.locator(selector).boundingBox()).y-old.y)<3,`${kind} undo must restore position`);
  }
  // Guard content which happens to match a UI label.
  await page.evaluate(()=>{const p=document.createElement('p');p.setAttribute('data-ui-content','');p.id='owned-content';p.textContent='Trabajos';document.body.append(p);I18n.set('de')});
  assert.equal(await page.locator('#owned-content').innerText(),'Trabajos');
  // Every requested language must fit both narrow and wide settings views.
  let count=0;
  for(const locale of Object.keys(heading))for(const width of [320,768,1536]){
   await page.setViewportSize({width,height:960});await page.evaluate(l=>I18n.set(l),locale);
   await page.evaluate(()=>go('settings'));await page.locator('#uiLanguage').waitFor();
   assert.equal(await page.locator('#uiLanguage').inputValue(),locale);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${locale} overflows ${width}`);count++;
  }
  // Leave the fixture ready for other browser checks.
  await page.request.delete(base+'/api/clips/'+clip.id+'/draft');
  assert.deepEqual(errors,[]);console.log(`Passed five locales, persistence, unchanged video content, all four text drag modes, save/reload/undo and ${count} responsive language layouts.`);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
