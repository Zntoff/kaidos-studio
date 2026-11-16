// Isolated fixture and mocked library additions; no user keys or paid calls.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const base=process.env.CLIPPER_QA_URL||'http://127.0.0.1:18765';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const context=await browser.newContext({permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>(errors.push(e.message),console.error(e.message)));
  await require('./session.cjs')(page,base);
  const jobs=await(await page.request.get(base+'/api/jobs')).json();
  const clips=await(await page.request.get(base+'/api/clips')).json();
  const projects=await(await page.request.get(base+'/api/projects')).json();
  assert.ok(jobs.length&&clips.length,'Synthetic fixture must have a job and a clip');
  await page.route('**/api/projects',async route=>{if(route.request().method()!=='GET')return route.continue();return route.fulfill({json:[...projects,{id:'qa_other',name:'Otro proyecto <QA>'}]});});
  await page.route(/\/api\/jobs(?:\?.*)?$/,route=>route.fulfill({json:[...jobs,{...jobs[0],id:'job_qa_other',project_id:'qa_other',status:'failed',summary:{error:'Error de prueba'}}]}));
  await page.addInitScript(()=>localStorage.setItem('kairos.uiLanguage','es'));
    await page.goto(base+'/#/jobs');await page.locator('.job-row').first().waitFor();
  const initial=await page.locator('.job-row').count();
  await page.locator('#jobsProject').selectOption('all');
  assert.equal(await page.locator('.job-row').count(),jobs.length+1);
  assert.ok(await page.getByRole('heading',{name:'Otro proyecto <QA>',exact:true}).isVisible());
  await page.locator('#jobsSearch').fill('job_qa_other');assert.equal(await page.locator('.job-row').count(),1);
  await page.locator('#jobsSearch').fill('');await page.locator('#jobsStatus').selectOption('failed');
  assert.ok(await page.locator('.job-row').count()>=1);await page.locator('#jobsStatus').selectOption('all');
  await page.locator('#jobsProject').selectOption('current');assert.equal(await page.locator('.job-row').count(),initial);
  let layouts=0;
  for(const theme of ['dark','light']){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
   for(const width of [320,390,768,1024,1280,1536,1920]){
    await page.setViewportSize({width,height:960});
    for(const view of ['jobs','apis']){
     await page.evaluate(v=>go(v),view);await page.locator(view==='jobs'?'#jobsSearch':'#aiProvider').waitFor();
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${view} overflow at ${width} ${theme}`);layouts++;
    }
    await page.evaluate(id=>clip(id),clips[0].id);await page.locator('.short-layout').waitFor();
    assert.equal(await page.locator('.publication-card').count(),3);
    assert.ok(await page.evaluate(()=>{const el=document.querySelector('.short-modal>.card');return el.scrollWidth<=el.clientWidth+1}),`Preview overflow at ${width}`);
    if(width>=1280){const rects=await page.locator('.short-layout>section').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().x));assert.ok(rects[0]<rects[1]&&rects[1]<rects[2]);}
    const copy=page.locator('[data-platform=youtube] [data-copy=all]');
    if(!await copy.isDisabled()){await copy.click();const text=await page.evaluate(()=>navigator.clipboard.readText());assert.ok(text.length>0);}
    await page.evaluate(()=>closeModal());layouts++;
   }
  }
  await page.evaluate(()=>go('apis'));await page.locator('#aiProvider').waitFor();
  await page.evaluate(()=>quickProvider());await page.locator('[data-switch=openai]').click();
  await page.locator('#aiCard[data-provider=openai]').waitFor();
  assert.equal(await page.locator('#modal').innerHTML(),'');
  assert.deepEqual(errors,[]);console.log(`${layouts} layouts passed; project filters, thumbnails, three-pane preview, clipboard and provider navigation passed.`);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
