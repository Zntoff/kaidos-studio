/* UI-only localization bridge for the shared legacy views. Never changes form values,
   persisted documents, generated content, API payloads or editor preview overlays. */
const I18n = (() => {
  const languages={en:'English',es:'Español',pt:'Português',fr:'Français',de:'Deutsch'};
  let locale='en',rows=new Map(),patterns=[],observer,scheduled=false;
  const originals=new WeakMap(),attributes=new WeakMap(),logs=new WeakMap();
  const normalize=s=>s.normalize('NFC').replace(/\s+/g,' ').replace(/\u2212/g,'-').trim();
  const assetQuery=document.currentScript?.src?.split('?')[1]||'';
  const uiArguments={'Ya generado · {0}':[0],'Modelo {0}':[0],'Precio de entrada {0}':[0],'Precio de salida {0}':[0],'Buscando momentos con {0}…':[0],'Generando {0} clip con {1}':[1],'Generando {0} clips con {1}':[1]};
  try{const saved=localStorage.getItem('kairos.uiLanguage');if(Object.hasOwn(languages,saved))locale=saved;}catch{}
  document.documentElement.lang=locale;
  const protectedContent='script,style,textarea,pre,code,video,canvas,[translate="no"],[data-ui-content],[data-ui-date],#edStage,.ttl,.publication-field p,.short-details>h2,.job-identity h3,#projectOverview,#dashboardProject,#projectSelect option,#moveProject option,#jobsProject option:not([value="current"]):not([value="all"]),[data-project]>span,.model-choice>span,.clip .hook,.cue .words,.cue .txt,.it[data-k="hook"],.it[data-k="note"],.it[data-k="text"],.it[data-k="cue"],.it[data-k="sfx"],.words [data-w],.itemrow[data-sel="text"] .tx,.itemrow[data-sel="note"] .tx,#dashboardResults strong,.src .nm,.src .fn,.dashboard-row strong';
  function known(source){const key=normalize(source);return rows.has(key)||patterns.some(p=>p.re.test(key));}
  function t(value) {
    if(typeof value!=='string')return value;
    const trimmed=value.trim(),key=normalize(trimmed),entry=rows.get(key);
    let translated=entry?.[locale];
    if(!translated)for(const p of patterns){const match=p.re.exec(key);if(match){translated=p.values[locale].replace(/\{(\d+)\}/g,(_,i)=>{
      const value=match[Number(i)+1]??'';return p.ui.includes(Number(i))?rows.get(normalize(value))?.[locale]??value:value;
    });break;}}
    return translated?value.replace(trimmed,translated):value;
  }
  function text(node) {
    const parent=node.parentElement;if(!parent||parent.closest(protectedContent))return;
    const old=originals.get(node),source=old&&node.nodeValue===old.result?old.source:node.nodeValue;
    const result=t(source); originals.set(node,{source,result});if(node.nodeValue!==result)node.nodeValue=result;
  }
  function apply(root=document.body) {
    if(!root)return;
    if(root.nodeType===Node.TEXT_NODE){text(root);return;}
    if(root.nodeType!==Node.ELEMENT_NODE)return;
    const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);while(walk.nextNode())text(walk.currentNode);
    for(const el of [root,...root.querySelectorAll('[title],[placeholder],[aria-label]')]){
      if(el.closest(protectedContent))continue;
      let saved=attributes.get(el);if(!saved){saved={};attributes.set(el,saved);}
      for(const key of ['title','placeholder','aria-label']){
        const current=el.getAttribute(key);if(current===null)continue;
        const source=saved[key]&&current===saved[key].result?saved[key].source:current,result=t(source);
        saved[key]={source,result};if(current!==result)el.setAttribute(key,result);
      }
    }
    root.querySelectorAll('[data-ui-language]').forEach(el=>{el.value=locale;el.onchange=()=>set(el.value);});
    root.querySelectorAll('[data-ui-date]').forEach(el=>{const result=date(el.dataset.uiDate,el.dataset.uiDateStyle);if(el.textContent!==result)el.textContent=result;});
    root.querySelectorAll('pre.log').forEach(el=>{
      const old=logs.get(el),source=old&&el.textContent===old.result?old.source:el.textContent;
      const result=source.split('\n').map(t).join('\n');logs.set(el,{source,result});if(el.textContent!==result)el.textContent=result;
    });
  }
  function date(value,style='datetime'){
    let source=String(value||'');
    if(/^\d{4}-\d{2}-\d{2}$/.test(source))source+='T12:00:00';
    else if(/^\d{4}-\d{2}-\d{2}T/.test(source)&&!/(?:Z|[+-]\d\d:\d\d)$/.test(source))source+='Z';
    const parsed=new Date(source);if(!Number.isFinite(parsed.getTime()))return value||'—';
    return new Intl.DateTimeFormat(locale,style==='date'?{dateStyle:'medium'}:{dateStyle:'medium',timeStyle:'short'}).format(parsed);
  }
  // Audit original UI strings, never video content, form values, model IDs or user names.
  function inspect(root=document.body){
    const missing=new Set(),add=source=>{if(source&&/\p{L}/u.test(source)&&!known(source))missing.add(source.trim());};
    const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    while(walk.nextNode()){const n=walk.currentNode;if(!n.parentElement?.closest(protectedContent))add(originals.get(n)?.source??n.nodeValue);}
    for(const el of root.querySelectorAll('[title],[placeholder],[aria-label]')){
      if(el.closest(protectedContent))continue;
      for(const k of ['title','placeholder','aria-label'])add(attributes.get(el)?.[k]?.source??el.getAttribute(k));
    }
    return [...missing].sort();
  }
  function set(value){
    if(!Object.hasOwn(languages,value))return;
    locale=value;document.documentElement.lang=locale;
    try{localStorage.setItem('kairos.uiLanguage',locale);}catch{}
    apply();window.dispatchEvent(new CustomEvent('kairos:language',{detail:locale}));
  }
  function control(id='uiLanguage'){
    return `<label for="${id}">Idioma de la interfaz</label><select id="${id}" data-ui-language aria-label="Idioma de la interfaz">${Object.entries(languages).map(([id,name])=>`<option value="${id}" translate="no" ${id===locale?'selected':''}>${name}</option>`).join('')}</select>`;
  }
  const ready=fetch('/static/locales.tsv'+(assetQuery?'?'+assetQuery:''),{cache:'no-cache'}).then(r=>{if(!r.ok)throw Error('Locale catalog unavailable');return r.text();}).then(data=>{
    for(const line of data.split(/\r?\n/)){
      if(!line.trim())continue;
      const cells=line.split('\t');if(cells.length!==5||cells.some(v=>!v.trim()))throw Error('Incomplete locale catalog row');
      const [es,en,pt,fr,de]=cells,values=Object.fromEntries(Object.entries({es,en,pt,fr,de}).map(([k,v])=>[k,v.trim()]));
      const placeholders=v=>[...v.matchAll(/\{\d+\}/g)].map(m=>m[0]).sort().join(',');
      if(Object.values(values).some(v=>placeholders(v)!==placeholders(es)))throw Error('Locale placeholders do not match: '+es);
      rows.set(normalize(es),values);rows.set(normalize(en),values);
      for(const source of [es,en])if(source.includes('{0}')){const escaped=normalize(source).replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/\\\{\d+\\\}/g,'(.*?)');patterns.push({re:new RegExp('^'+escaped+'$'),values,ui:uiArguments[es]||[]});}
    }
    return new Promise(resolve=>{const init=()=>{
      const footer=document.querySelector('.sidebar-footer');
      if(footer&&!document.querySelector('#uiLanguageNav')){const holder=document.createElement('div');holder.id='uiLanguageNav';holder.innerHTML=control('uiLanguageQuick');footer.prepend(holder);}
      apply();
      observer=new MutationObserver(changes=>{
        if(scheduled)return;scheduled=true;
        queueMicrotask(()=>{scheduled=false;observer.disconnect();apply();observe();});
      });
      function observe(){observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','placeholder','aria-label']});}
      observe();resolve();
    };if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();});
  }).catch(error=>{console.error(error.message);});
  window.addEventListener('storage',e=>{if(e.key==='kairos.uiLanguage'&&e.newValue!==locale&&Object.hasOwn(languages,e.newValue))set(e.newValue);});
  return {t,set,control,ready,inspect,known,date,number:(n,options)=>new Intl.NumberFormat(locale,options).format(n),get locale(){return locale;},confirm:value=>window.confirm(Array.isArray(value)?value.map(t).join(' '):t(value))};
})();
