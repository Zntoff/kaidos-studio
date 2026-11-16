// End-to-end workspace behavior. Run against serve_ui.py's isolated synthetic library.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path'),fs=require('node:fs');
const base=process.env.CLIPPER_QA_URL||'http://127.0.0.1:18765';
const output=process.env.CLIPPER_QA_OUTPUT||path.join(process.env.TEMP,'kairos-workspace-qa');
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],starts=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST' && r.url().includes('/api/jobs'))starts.push(r.url());});
    await page.addInitScript(()=>localStorage.setItem('kairos.uiLanguage','es'));
  await require('./session.cjs')(page,base);
    await page.goto(base);
    await page.locator('#dashboardSearch').waitFor();
    assert.equal(await page.locator('#dashboardTitle').innerText(),'¿Qué quieres hacer hoy?');
    const projectA=(await (await page.request.post(base+'/api/projects',{data:{name:'QA Alpha '+Date.now()}})).json()).id;
    const projectB=(await (await page.request.post(base+'/api/projects',{data:{name:'QA Beta '+Date.now()}})).json()).id;
    await page.evaluate(async id=>{await loadProjects();switchProject(id,'dashboard');},projectA);
    await page.locator('#dashboardSearch').waitFor();
    await page.locator('[data-action=short]').click();
    await page.getByText('Este proyecto aún no tiene videos.',{exact:true}).waitFor();
    await page.locator('#shortAddVideo').click();
    await page.locator('#up').waitFor();
    await page.goto(base+'/#/resources');await page.locator('#resourceForm').waitFor();
    const name='private-alpha-notes.txt';
    await page.locator('#resourceFile').setInputFiles({name,mimeType:'text/plain',buffer:Buffer.from('Exclusive Alpha resource')});
    await page.locator('#resourceDescription').fill('Reference for Alpha only');
    await page.locator('#resourceForm button').click();
    await page.getByRole('heading',{name,exact:true}).waitFor();
    await page.goto(base+'/#/dashboard');await page.locator('#dashboardSearch').waitFor();
    await page.locator('#dashboardSearch').fill('private-alpha');
    await page.locator('.search-result').filter({hasText:name}).waitFor();
    await page.evaluate(id=>switchProject(id),projectB);
    await page.locator('#dashboardSearch').waitFor();
    await page.locator('#dashboardSearch').fill('private-alpha');
    await page.getByText('Sin resultados en este proyecto.',{exact:true}).waitFor();
    await page.goto(base+'/#/resources');await page.locator('#resourceForm').waitFor();
    assert.equal(await page.locator('.resource-card').count(),0,'Resource leaked to another project');
    // A late response for a previous project must not replace the active project view.
    await page.route('**/api/sources?project_id='+projectA,async route=>{
      await new Promise(resolve=>setTimeout(resolve,250));await route.continue();
    });
    await page.evaluate(([a,b])=>{switchProject(a,'videos');setTimeout(()=>switchProject(b,'dashboard'),20);},[projectA,projectB]);
    await page.locator('#dashboardSearch').waitFor();
    await page.waitForTimeout(350);
    assert.ok(await page.locator('#dashboardSearch').isVisible(),'Late source response replaced dashboard');
    await page.unroute('**/api/sources?project_id='+projectA);
    // Generate action shows only this project's sources and performs no paid work by itself.
    await page.evaluate(()=>switchProject('project_default','dashboard'));
    await page.locator('#dashboardSearch').waitFor();
    await page.locator('[data-action=short]').click();
    assert.ok(await page.locator('.short-source').count()>0);
    assert.equal(starts.length,0,'Opening dashboard or chooser must never start generation');
    await page.locator('#modal .x').click();
    // Rail mode gives content back its space, while preserving project switching and settings.
    const expanded=await page.locator('#main').boundingBox();
    await page.locator('#sidebarToggle').click();
    assert.ok(await page.locator('#projectQuick').isVisible());
    const compact=await page.locator('#main').boundingBox();
    assert.ok(compact.width>expanded.width+100);
    await page.locator('#projectQuick').click();await page.locator('.project-chooser').waitFor();
    await page.locator('#modal .x').click();await page.locator('#sidebarToggle').click();
    let checks=0;
    for(const [width,height] of [[320,568],[360,480],[600,600],[768,600],[1024,600],[1280,720],[1920,1080]]){
      await page.setViewportSize({width,height});await page.goto(base+'/#/dashboard');await page.locator('#dashboardSearch').waitFor();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow at '+width);
      if(width<768)await page.locator('#mobileMenu').click();
      const areas=await page.locator('#sidebar').evaluate(side=>['.sidebar-brand','.sidebar-project','.sidebar-scroll','.sidebar-footer'].map(s=>{const b=side.querySelector(s).getBoundingClientRect();return {top:b.top,bottom:b.bottom,left:b.left,right:b.right};}));
      for(let i=1;i<areas.length;i++)assert.ok(areas[i-1].bottom<=areas[i].top+1,`Sidebar areas overlap at ${width}x${height}: ${JSON.stringify(areas)}`);
      for(const name of ['Inicio','Proyectos','Videos','Recursos','Trabajos','Clips','Cola de aprobación']){
        const button=page.locator('#nav').getByRole('button',{name,exact:true});
        await button.scrollIntoViewIfNeeded();
        const box=await button.boundingBox();assert.ok(box.y>=0 && box.y+box.height<=height+1,`Unreachable ${name} at ${width}x${height}`);
      }
      assert.ok(await page.locator('#cfg').isVisible());
      if(width<768){
        await page.locator('#nav').getByRole('button',{name:'Recursos',exact:true}).click();
        await page.locator('#resourceForm').waitFor();
        await page.locator('#sidebar').waitFor({state:'hidden'});
        await page.locator('#mobileMenu').click();await page.keyboard.press('Escape');
        await page.locator('#sidebar').waitFor({state:'hidden'});
      }
      await page.goto(base+'/#/dashboard');await page.locator('#dashboardSearch').waitFor();
      await page.evaluate(()=>document.fonts.ready);
      await page.screenshot({path:path.join(output,`dashboard-${width}.png`),fullPage:true});
      checks++;
    }
    assert.deepEqual(errors,[]);
    console.log(`Passed dashboard actions, scoped search/resources, stale-response protection, sidebar controls and ${checks} viewport/height combinations.`);
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
