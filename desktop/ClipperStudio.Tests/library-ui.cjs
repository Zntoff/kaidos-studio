// Project-scoped imports/deletion in the isolated fixture; URL downloads are intercepted.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.CLIPPER_QA_URL||'http://127.0.0.1:18765';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)});
  await require('./session.cjs')(page,base);
  const project=await(await page.request.post(base+'/api/projects',{data:{name:'Import and delete '+Date.now()}})).json();
  await page.goto(base+'/#/dashboard');await page.evaluate(()=>I18n.ready);
  await page.evaluate(async id=>{await loadProjects();switchProject(id,'dashboard')},project.id);
  await page.locator('#dashboardAdd').waitFor();await page.locator('#dashboardAdd').click();
  await page.locator('[data-import-mode=local]').click();
  await page.locator('#importFile').setInputFiles({name:'brief.txt',mimeType:'text/plain',buffer:Buffer.from('Reference file')});
  await page.locator('#importDescription').fill('Private supporting file');await page.locator('#importSubmit').click();
  await page.locator('.resource-card').waitFor();
  assert.equal((await(await page.request.get(base+`/api/projects/${project.id}/resources`)).json()).length,1);
  await page.getByRole('button',{name:'Delete resource',exact:true}).click();await page.locator('#deleteCancel').click();
  assert.equal(await page.locator('.resource-card').count(),1,'Cancel must preserve the resource');
  await page.getByRole('button',{name:'Delete resource',exact:true}).click();await page.locator('#deleteConfirm').click();
  await page.locator('.resource-card').waitFor({state:'detached'});
  await page.evaluate(()=>go('dashboard'));await page.locator('#dashboardAdd').click();await page.locator('[data-import-mode=local]').click();
  await page.locator('#importFile').setInputFiles(path.join(process.env.TEMP,'kairos-workspace-fixture','workspace-demo.mp4'));
  await page.locator('#importRightsStatus').selectOption('own');await page.locator('#importEvidence').fill('Synthetic fixture created for testing');
  await page.locator('#importSubmit').click();await page.locator('.src').waitFor();
  const sources=await(await page.request.get(base+`/api/sources?project_id=${project.id}`)).json();assert.equal(sources.length,1);
  await page.getByRole('button',{name:'Delete video',exact:true}).click();await page.locator('#deleteConfirm').click();
  await page.locator('.src').waitFor({state:'detached'});
  const calls=[];
  await page.route('**/api/sources/from-url',async route=>{calls.push(route.request().postData());await route.fulfill({json:{run_id:'mock-download'}})});
  for(const url of ['https://www.youtube.com/watch?v=synthetic','https://www.twitch.tv/videos/1234']){
   await page.evaluate(()=>go('dashboard'));await page.locator('#dashboardAdd').click();
   await page.locator('#importUrl').fill(url);await page.locator('#importRightsStatus').selectOption('own');await page.locator('#importEvidence').fill('Permission evidence for test');
   await page.locator('#importSubmit').click();await page.locator('#jobsSearch').waitFor();
  }
  assert.equal(calls.length,2);assert.ok(calls.every(c=>c.includes(project.id)));
  await page.evaluate(()=>go('projects'));
  const card=page.locator('.project-card').filter({has:page.getByRole('heading',{name:project.name,exact:true})});
  await card.getByRole('button',{name:'Delete project',exact:true}).click();await page.locator('#deleteConfirm').click();
  await card.waitFor({state:'detached'});
  const projects=await(await page.request.get(base+'/api/projects')).json();assert.ok(!projects.some(p=>p.id===project.id));
  for(const width of [320,768,1440]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>go('dashboard'));await page.locator('#dashboardAdd').click();
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Import overflows at '+width);await page.evaluate(()=>closeModal());
  }
  assert.deepEqual(errors,[]);console.log('Passed local video/reference imports, YouTube/Twitch routing, delete/cancel for resources/videos/projects and three import layouts. No real downloads or AI calls.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
