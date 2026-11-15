/* Shared desktop/container views. Provider requests never run merely by opening a view. */
const JobsView = (() => {
  let scope = 'current', status = 'all', query = '', ticket = 0;
  async function open() {
    clearInterval(timer);
    const epoch = viewEpoch, project = currentProject, request = ++ticket;
    const [jobs, runs, sources] = await Promise.all(['/api/jobs','/api/runs','/api/sources'].map(u=>api(u,{allProjects:true})));
    const valid = () => epoch === viewEpoch && project === currentProject && tab === 'jobs' && ticket === request;
    if (!valid()) return;
    const sourceMap = new Map(sources.map(s=>[s.id,s]));
    const title = j => nameOfSource(sourceMap.get(j.source_id) || {id:j.source_id});
    const inScope = j => scope === 'all' || (j.project_id || 'project_default') === (scope === 'current' ? currentProject : scope);
    const visible = () => jobs.filter(j=>inScope(j) && (status==='all' || (status==='active' ? ['queued','running','awaiting_selection'].includes(j.status) : status==='failed' ? ['failed','interrupted'].includes(j.status) : j.status==='done')) && searchText([title(j),j.id,projects.find(p=>p.id===j.project_id)?.name].join(' ')).includes(searchText(query))).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
    $('#main').innerHTML = `<div class="page jobs-page">${head('Trabajos','Encuentra cada generación por su video, estado y proyecto.')}<div class="jobs-toolbar card"><div><label for="jobsSearch">Buscar un trabajo</label><input id="jobsSearch" type="search" placeholder="Video, proyecto o identificador" value="${esc(query)}"></div><div><label for="jobsProject">Proyecto</label><select id="jobsProject"><option value="current">Proyecto actual · ${esc(projectName())}</option><option value="all">Todos los proyectos</option>${projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></div><div><label for="jobsStatus">Estado</label><select id="jobsStatus"><option value="all">Todos los estados</option><option value="active">En curso y por elegir</option><option value="done">Terminados</option><option value="failed">Con errores</option></select></div></div><div id="jobsSummary" class="jobs-summary" role="status"></div><div id="jobRuns"></div><div id="jobGroups"></div></div>`;
    const draw = () => {
      const filtered = visible();
      $('#jobsSummary').textContent = `${filtered.length} de ${jobs.length} trabajos · ${jobs.filter(j=>inScope(j)&&j.status==='done').length} terminados · ${jobs.filter(j=>inScope(j)&&['failed','interrupted'].includes(j.status)).length} requieren atención`;
      const live = runs.filter(r=>inScope(r)&&['queued','running','failed'].includes(r.status));
      $('#jobRuns').innerHTML = live.filter(r=>r.status!=='failed').map(r=>`<details class="card run-card"><summary>${pill(r.status)} ${esc(r.label)}</summary><pre class="log" data-run="${esc(r.id)}">${esc((r.log||[]).join('\n'))}</pre></details>`).join('');
      const ids = [...new Set(filtered.map(j=>j.project_id||'project_default'))];
      $('#jobGroups').innerHTML = ids.map(pid=>`<section class="job-project"><div class="job-group-head"><h2 data-ui-content>${esc(projects.find(p=>p.id===pid)?.name||'General')}</h2><span class="mut sm">${filtered.filter(j=>(j.project_id||'project_default')===pid).length} trabajos</span></div><div class="job-list">${filtered.filter(j=>(j.project_id||'project_default')===pid).map(j=>{
        const sid=sourceMap.has(j.source_id)?j.source_id:null;
        const counts=Object.entries(j.clip_counts||{}).map(([k,v])=>`${v} ${(STATUS[k]||[k])[0].toLowerCase()}`).join(' · ');
        const error=j.summary?.error || live.find(r=>r.job_id===j.id&&r.status==='failed')?.error;
        return `<article class="job-row"><div class="job-thumb">${icon('film')}${sid?`<img loading="lazy" src="/api/sources/${encodeURIComponent(sid)}/frame?t=1&h=128" alt="Miniatura de ${esc(title(j))}" onerror="this.remove()">`:''}</div><div class="job-identity"><h3>${esc(title(j))}</h3><div class="mut sm"><time data-ui-date="${esc(j.created_at)}">${esc(I18n.date(j.created_at))}</time> · <code>${esc(j.id)}</code></div><div class="sm">${esc(counts||'Aún sin clips')}</div>${error?`<details class="job-error"><summary>Ver el error</summary><p>${esc(error)}</p></details>`:''}</div><div class="job-state">${pill(j.status)}</div><div class="job-actions"><button class="b g sm" data-job="${esc(j.id)}">Ver trabajo</button>${['failed','interrupted'].includes(j.status)?`<button class="b sm" data-resume="${esc(j.id)}">Retomar</button>`:j.status==='awaiting_selection'?`<button class="b sm" data-select="${esc(j.id)}">Elegir momentos</button>`:j.status==='done'&&j.options?.review?`<button class="b g sm" data-select="${esc(j.id)}">Generar más</button>`:''}</div></article>`;
      }).join('')}</div></section>`).join('') || empty('pulse',jobs.length?'No hay trabajos con estos filtros.':'Todavía no hay trabajos en este proyecto.');
      $$('[data-job]').forEach(b=>b.onclick=()=>job(b.dataset.job).catch(e=>toast(e.message,'er')));
      $$('[data-resume]').forEach(b=>b.onclick=()=>resume(b.dataset.resume));
      $$('[data-select]').forEach(b=>b.onclick=()=>go('select/'+b.dataset.select));
    };
    $('#jobsProject').value=scope; $('#jobsStatus').value=status;
    $('#jobsProject').onchange=e=>{scope=e.target.value;draw()};
    $('#jobsStatus').onchange=e=>{status=e.target.value;draw()};
    $('#jobsSearch').oninput=e=>{query=e.target.value;draw()}; draw();
    const fingerprint = JSON.stringify([jobs,runs.map(r=>[r.id,r.status,r.error])]);
    let polling=false;
    timer=setInterval(async()=>{
      if (!valid()||polling) return; polling=true;
      try {
        const [js,rs]=await Promise.all(['/api/jobs','/api/runs'].map(u=>api(u,{allProjects:true})));
        if (!valid()) return;
        if(JSON.stringify([js,rs.map(r=>[r.id,r.status,r.error])])!==fingerprint && !$('#modal').firstChild && document.activeElement!==$('#jobsSearch')) { await open(); return; }
        for(const r of rs.filter(r=>['queued','running'].includes(r.status))) {
          const full=await api('/api/runs/'+encodeURIComponent(r.id));
          if(!valid())return;
          const el=$$('[data-run]').find(e=>e.dataset.run===r.id);if(el)el.textContent=(full.log||[]).join('\n');
        }
      }catch(e){ if(valid())$('#jobsSummary').textContent='No se pudo actualizar el estado. Reintentando…'; }
      finally{polling=false;}
    },3000);
  }
  return {open};
})();

async function copyPublishing(text) {
  try {
    if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else {const field=document.createElement('textarea');field.value=text;field.style.position='fixed';document.body.append(field);field.select();const ok=document.execCommand('copy');field.remove();if(!ok)throw Error('copy');}
    toast('Copiado al portapapeles','ok');
  } catch {toast('No se pudo copiar. Selecciona el texto y cópialo manualmente.','er');}
}
function publishingCards(c, language) {
  const metadata=c.metadata?.[language]||{};
  const targets=[['youtube','YouTube Shorts'],['instagram','Instagram Reels'],['tiktok','TikTok']];
  $('#publishCards').innerHTML=targets.map(([id,name])=>{
    const m=metadata[id]||{},tags=(m.hashtags||[]).map(h=>'#'+String(h).replace(/^#+/,'')).join(' ');
    return `<article class="publication-card" data-platform="${id}"><header><h3>${name}</h3><button class="b g sm" data-copy="all">Copiar todo</button></header>${[['title','Título',m.title],['description','Descripción',m.description],['hashtags','Hashtags',tags]].map(([field,label,value])=>`<div class="publication-field"><div><b>${label}</b><button class="b g sm" data-copy="${field}" ${!value?'disabled':''} aria-label="Copiar ${label.toLowerCase()} de ${name}">Copiar</button></div><p>${esc(value||'Sin sugerencia generada')}</p></div>`).join('')}</article>`;
  }).join('');
  $$('.publication-card').forEach(card=>{
    const m=metadata[card.dataset.platform]||{}, values={title:m.title||'',description:m.description||'',hashtags:(m.hashtags||[]).map(h=>'#'+String(h).replace(/^#+/,'')).join(' ')};
    const all=Object.values(values).filter(Boolean).join('\n\n');
    $$('[data-copy]',card).forEach(b=>{b.disabled=!all||b.dataset.copy!=='all'&&!values[b.dataset.copy];b.onclick=()=>copyPublishing(b.dataset.copy==='all'?all:values[b.dataset.copy]);});
  });
}

let apisRequest=0;
async function vApis() {
  const request=++apisRequest,epoch=viewEpoch,st=await api('/api/settings/ai'); if(tab!=='apis'||epoch!==viewEpoch||request!==apisRequest)return;
  $('#main').innerHTML=`<div class="page apis-page">${head('APIs y modelos','Tus conexiones de IA, sus modelos y el proveedor que usarás en las próximas generaciones.', '<button class="b g" onclick="quickProvider()">Cambiar proveedor</button>')}<div class="provider-grid">${st.providers.map(p=>`<button class="provider-tile ${p.id===(aiPick||st.provider)?'selected':''}" data-pick="${esc(p.id)}"><b>${esc(p.name)}</b><span class="mut sm">${p.id===st.provider?'En uso · ':''}${p.missing?'Por configurar':'Listo para usar'}</span><span class="sm">${p.needs_key?(p.key_set?'Key conectada':'Sin key'):'Servidor local o compatible'} · ${Object.values(p.models).filter(Boolean).length}/3 niveles</span></button>`).join('')}</div>${aiCard(st)}</div>`;
  const msg=(text)=>{if($('#keyMsg'))$('#keyMsg').innerHTML=text?`<div class="msg">${text}</div>`:''};
  const busy=(b,on,text)=>{if(!b)return;if(on){b.dataset.label=b.innerHTML;b.textContent=text||'Guardando…'}else if(b.dataset.label)b.innerHTML=b.dataset.label;b.disabled=on};
  bindAiCard(st,msg,busy);
  $$('[data-pick]').forEach(b=>b.onclick=()=>{aiPick=b.dataset.pick;vApis().catch(showViewError)});
}
function renderModelCatalog(p,list) {
  const root=$('#modelCatalog');if(!root)return;
  root.innerHTML=`<div class="model-catalog"><b>${list.length} modelos disponibles en esta conexión</b><p class="mut sm">Busca un modelo y asígnalo a los niveles que quieras usar. Guarda los cambios para aplicarlos. La disponibilidad de generación depende de los permisos y el saldo de tu cuenta; elige modelos de conversación compatibles con texto e imágenes.</p><input type="search" id="modelSearch" placeholder="Buscar modelo" aria-label="Buscar modelos disponibles"><div class="model-options"></div><div class="mut sm" id="selectedModels"></div></div>`;
  const selected=()=>{ $('#selectedModels').textContent='Se usarán: '+[...new Set($$('[data-model]').map(i=>i.value.trim()).filter(Boolean))].join(' · '); };
  const draw=()=>{
    const matches=list.filter(m=>searchText(m).includes(searchText($('#modelSearch').value)));
    $('.model-options',root).innerHTML=matches.slice(0,100).map(m=>`<div class="model-choice"><span>${esc(m)}</span><div class="model-assign">${TIER_IDS.map(t=>`<button class="b g sm" data-assign="${t}" data-id="${esc(m)}" title="Usar ${esc(m)} en ${esc(p.tier_names[t])}">${esc(p.tier_names[t])}</button>`).join('')}</div></div>`).join('')+(matches.length>100?'<p class="mut sm">Mostrando 100 resultados. Busca para encontrar los demás.</p>':'');
    $$('[data-assign]',root).forEach(b=>b.onclick=()=>{$(`[data-model="${b.dataset.assign}"]`).value=b.dataset.id;selected();toast('Modelo asignado. Guarda los cambios para aplicarlo.');});selected();
  };
  $('#modelSearch').oninput=draw;$$('[data-model]').forEach(i=>i.oninput=selected);draw();
}
async function quickProvider() {
  try {
    const epoch=viewEpoch,st=await api('/api/settings/ai'); if(epoch!==viewEpoch)return;
    modal(`<h2>Cambiar proveedor de IA</h2><p class="mut sm">Se aplica a las próximas generaciones. Los trabajos en curso conservan su configuración.</p><div class="provider-switch">${st.providers.map(p=>`<button class="b g" data-switch="${esc(p.id)}"><span>${esc(p.name)}${p.id===st.provider?' · En uso':''}</span><span class="mut sm">${p.missing?'Configurar':'Usar proveedor'}</span></button>`).join('')}</div>`);
    $$('[data-switch]').forEach(b=>b.onclick=async()=>{
      const p=st.providers.find(p=>p.id===b.dataset.switch);
      if(p.missing){aiPick=p.id;closeModal();go('apis');return;}
      b.disabled=true;
      try{await send('PUT','/api/settings/ai/provider',{provider:p.id,activate:true});cfg=await api('/api/config');paintCfg();closeModal();toast(`Proveedor activo: ${p.name}`,'ok'); if(tab==='apis'||tab==='settings')render().catch(showViewError);}
      catch(e){b.disabled=false;toast(e.message,'er');}
    });
  }catch(e){toast(e.message,'er')}
}
