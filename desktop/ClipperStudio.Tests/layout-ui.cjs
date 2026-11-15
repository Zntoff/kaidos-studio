// Browser regression tests against an isolated local test server (never the user's library).
// PLAYWRIGHT_MODULE points to a dev installation of playwright; CLIPPER_QA_URL defaults to localhost.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const base = process.env.CLIPPER_QA_URL || 'http://127.0.0.1:18765';
const output = process.env.CLIPPER_QA_OUTPUT || path.join(process.env.TEMP, 'clipper-ui-qa');
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage(); const errors=[];
    page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});
    await page.addInitScript(()=>localStorage.setItem('kairos.uiLanguage','es'));
  await require('./session.cjs')(page,base);
    await page.goto(base+'/#/projects');
    await page.locator('#main').getByRole('button',{name:'Nuevo proyecto',exact:true}).click();
    const name='Proyecto <QA> '+Date.now();
    await page.locator('#projectName').fill(name);
    await page.locator('#projectDescription').fill('Videos y generaciones del proyecto de prueba.');
    await page.getByRole('button',{name:'Guardar proyecto',exact:true}).click();
    await page.locator('#modal').filter({has:page.locator('form')}).waitFor({state:'hidden'});
    await page.getByRole('heading',{name,exact:true}).waitFor();
    const selected=await page.locator('#projectSelect').inputValue();
    await page.goto(base+'/#/videos');
    await page.getByRole('heading',{name:'Videos',exact:true}).waitFor();
    assert.match(await page.locator('#main').innerText(),/Aún no hay videos/);
    await page.locator('#projectSelect').selectOption('project_default');
    await page.locator('.src').first().waitFor();
    await page.request.put(base+'/api/settings/ai/budget',{data:{usd:25}});
    await page.evaluate(()=>paintCfg());
    assert.match(await page.locator('#cfg').innerText(),/Crédito restante/i);
    const routes={dashboard:'¿Qué quieres hacer hoy?',projects:'Proyectos',resources:'Recursos',videos:'Videos',jobs:'Trabajos',clips:'Clips',queue:'Cola de aprobación',settings:'Ajustes'};
    async function checkNavigation(width) {
      if(width<768) await page.locator('#mobileMenu').click();
      assert.ok(await page.locator('#cfg').isVisible(),'Usage must be reachable in navigation');
      assert.ok(await page.locator('#projectSelect').isVisible() || await page.locator('#projectQuick').isVisible(),'Project switch must be reachable');
      for(const label of ['Inicio','Proyectos','Videos','Recursos','Trabajos','Clips','Cola de aprobación'])
        assert.ok(await page.locator('#nav').getByRole('button',{name:label,exact:true}).isVisible(),label+' must be reachable');
      if(width<768)await page.locator('#sidebarToggle').click();
    }
    let checks=0;
    for(const width of [360,768,1280,1920]) {
      await page.setViewportSize({width,height:900});
      for(const [route,title] of Object.entries(routes)) {
        await page.goto(base+'/#/'+route);
        await page.getByRole('heading',{name:title,exact:true}).waitFor();
        if(route==='settings') await page.locator('#saveRender').waitFor();
        const overflow=await page.evaluate(()=>({body:document.documentElement.scrollWidth,width:innerWidth}));
        assert.ok(overflow.body<=overflow.width+1,`${route} overflows at ${width}: ${JSON.stringify(overflow)}`);
        await checkNavigation(width);
        checks++;
      }
      await page.screenshot({path:path.join(output,`settings-${width}.png`),fullPage:true});
    }
    await page.locator('#renderDevice').selectOption('cpu');
    await page.locator('#saveRender').click();
    await page.getByText('Rendimiento guardado',{exact:true}).waitFor();
    const clips=await (await page.request.get(base+'/api/clips')).json();
    const clip=clips.find(c=>c.edl && ['approved','needs_human','pending_approval'].includes(c.status));
    assert.ok(clip,'QA fixture must contain an editable clip');
    for(const width of [360,768,1280]) {
      await page.setViewportSize({width,height:900});
      await page.goto(base+'/#/editor/'+clip.id);
      await page.locator('#edStage').waitFor();
      if(width<=1000) {
        await page.locator('[data-panel=tools]').click();
        assert.ok(await page.locator('.ed-side').isVisible());
        await page.locator('[data-panel=inspector]').click();
        assert.ok(await page.locator('.ed-insp').isVisible());
        await page.locator('[data-panel=preview]').click();
      } else {
        assert.ok(await page.locator('.ed-side').isVisible());
        assert.ok(await page.locator('.ed-insp').isVisible());
      }
      await page.screenshot({path:path.join(output,`editor-${width}.png`)});
      assert.ok(await page.locator('[data-a=render]').isVisible());
      checks++;
    }
    await page.goto(base+'/#/settings');
    await page.locator('#appearanceTheme').waitFor();
    assert.equal(await page.title(),'Kairos Studio');
    await page.evaluate(()=>document.fonts.ready);
    assert.ok(await page.evaluate(()=>document.fonts.check('400 32px "Instrument Serif"')),'Brand heading font must load locally');
    assert.ok(await page.evaluate(()=>document.fonts.check('500 14px Inter')),'Interface font must load locally');
    assert.ok(await page.evaluate(()=>document.fonts.check('400 12px "JetBrains Mono"')),'Time font must load locally');
    for(const theme of ['light','dark']) {
      await page.locator('#appearanceTheme').selectOption(theme);
      await page.reload(); await page.locator('#appearanceTheme').waitFor();
      assert.equal(await page.locator('#appearanceTheme').inputValue(),theme,'Theme preference must survive reload');
      assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme);
      const expected=theme==='light'?'rgb(255, 255, 255)':'rgb(0, 0, 0)';
      assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor),expected);
      assert.ok(await page.locator(theme==='light'?'.brand .brand-lockup.brand-light':'.brand .brand-lockup.brand-dark').isVisible());
      for(const width of [360,1280]) {
        await page.setViewportSize({width,height:900});
        for(const [route,title] of Object.entries(routes)) {
          await page.goto(base+'/#/'+route);
          await page.getByRole('heading',{name:title,exact:true}).waitFor();
          const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
          assert.ok(overflow<=1,`${theme} ${route} overflows at ${width}`);
          checks++;
        }
        await page.evaluate(()=>document.fonts.ready);
        await page.screenshot({path:path.join(output,`kairos-${theme}-${width}.png`),fullPage:true});
        await page.goto(base+'/#/editor/'+clip.id);await page.locator('#edStage').waitFor();
        await page.evaluate(()=>document.fonts.ready);
        await page.waitForFunction(()=>{const a=document.querySelector('#edBox').getBoundingClientRect(),b=document.querySelector('#edWrap').getBoundingClientRect();return a.top>=b.top-1 && a.bottom<=b.bottom+1;});
        await page.evaluate(()=>{const e=Editor.state;e.t=e.doc.start+1;document.querySelector('#edVid').currentTime=e.t;Editor.tick();});
        await page.screenshot({path:path.join(output,`kairos-editor-${theme}-${width}.png`)});
      }
      await page.goto(base+'/#/settings');await page.locator('#appearanceTheme').waitFor();
    }
    await page.emulateMedia({colorScheme:'light'});
    await page.locator('#appearanceTheme').selectOption('system');
    assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'light');
    await page.emulateMedia({colorScheme:'dark'});
    await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
    assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'dark');
    assert.deepEqual(errors,[],`Frontend errors: ${errors.join('; ')}`);
    console.log(`Passed project creation, isolation, credit display, CPU settings and ${checks} responsive views.`);
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
