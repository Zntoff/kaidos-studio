/* Explicit, project-scoped imports and recoverable library removal. */
async function deleteLibrary(kind,id,name) {
  const descriptions={projects:'Deleting a project also removes its videos, jobs, shorts and resources.',sources:'Deleting a video also removes its jobs and shorts.',clips:'This short and its editor draft will be removed.',resources:'This supporting file will be removed from the project.'};
  modal(`<h2>Delete from library?</h2><p data-ui-content>${esc(name||id)}</p><p>${esc(descriptions[kind])}</p><p class="mut sm">Managed files move to the local recovery folder. Originals outside Kairos are kept.</p><div class="dialog-actions"><button class="b g" id="deleteCancel">Cancel</button><button class="b er" id="deleteConfirm">Delete</button></div><p id="deleteError" class="mut sm" role="alert"></p>`);
  const dialog=$('#modal').firstElementChild,epoch=viewEpoch;
  $('#deleteCancel').onclick=closeModal;
  $('#deleteConfirm').onclick=async e=>{
    e.target.disabled=true;
    try {
      await send('DELETE',`/api/library/${kind}/${encodeURIComponent(id)}`);
      if(dialog.isConnected)closeModal();
      await loadProjects();
      if(epoch===viewEpoch){if(tab==='editor')go('clips');else render().catch(showViewError);}
      toast('Removed from library. Managed files are kept in the recovery folder.','ok');
    }catch(error){if(dialog.isConnected){$('#deleteError').textContent=error.message;e.target.disabled=false;}else toast(error.message,'er');}
  };
}
function importResources(mode='url') {
  const project=currentProject;
  modal(`<h2>Add to this project</h2><p class="mut sm" data-ui-content>${esc(projectName())}</p><div class="import-modes"><button class="b g ${mode==='url'?'on':''}" data-import-mode="url">YouTube / Twitch</button><button class="b g ${mode==='local'?'on':''}" data-import-mode="local">From computer</button></div><form id="importForm">${mode==='url'?'<label for="importUrl">Video link</label><input id="importUrl" name="url" type="url" required placeholder="https://www.youtube.com/watch?v=…">':'<label for="importFile">Video or supporting file</label><input id="importFile" type="file" required accept="video/*,image/png,image/jpeg,image/webp,image/gif,audio/*,.pdf,.txt,.md,.json"><p class="mut sm">Videos join your video library. Images, audio and documents join Resources.</p>'}<div id="importRights"><label for="importRightsStatus">Rights status</label><select id="importRightsStatus" name="rights" required><option value="" disabled selected>Select rights status</option>${(cfg.rights||[]).map(r=>`<option value="${esc(r)}">${esc(rightsLabel(r))}</option>`).join('')}</select><label for="importEvidence">Permission evidence</label><input id="importEvidence" name="evidence" minlength="8" required><label for="importCredit">Credit (optional)</label><input id="importCredit" name="credit"><label for="importSpoken">Spoken language</label><select id="importSpoken" name="language"><option value="">Detect</option>${[['en','English'],['es','Español'],['pt','Português'],['fr','Français'],['de','Deutsch']].map(([id,name])=>`<option value="${id}" translate="no">${name}</option>`).join('')}</select></div><div id="importReference" hidden><label for="importDescription">Description (optional)</label><input id="importDescription" maxlength="600"></div><div class="dialog-actions"><button type="submit" class="b" id="importSubmit">Add to project</button><button type="button" class="b g" id="importCancel">Cancel</button></div><p id="importMessage" role="status" class="mut sm"></p></form>`);
  const form=$('#importForm'),isVideo=file=>!!file&&(file.type.startsWith('video/')||/\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name));
  $$('[data-import-mode]').forEach(b=>b.onclick=()=>importResources(b.dataset.importMode));
  $('#importCancel').onclick=closeModal;
  const update=()=>{
    const video=mode==='url'||isVideo($('#importFile')?.files[0]);
    $('#importRights').hidden=!video;$('#importReference').hidden=video;
    $$('#importRights input,#importRights select').forEach(el=>el.disabled=!video);
  };
  if($('#importFile'))$('#importFile').onchange=update;
  update();
  form.onsubmit=async e=>{
    e.preventDefault();const button=$('#importSubmit');button.disabled=true;
    try{
      const data=new FormData(form);data.set('project_id',project);
      let destination;
      if(mode==='url'){await api('/api/sources/from-url',{method:'POST',body:data});destination='jobs';}
      else{
        const file=$('#importFile').files[0];if(!file)throw Error('Choose a file first.');
        data.set('file',file);
        if(isVideo(file)){await api('/api/sources/upload',{method:'POST',body:data});destination='videos';}
        else{data.set('description',$('#importDescription').value);await api(`/api/projects/${project}/resources`,{method:'POST',body:data});destination='resources';}
      }
      if(form.isConnected){closeModal();go(destination);}toast('Added to your project.','ok');
    }catch(error){if(form.isConnected){$('#importMessage').textContent=error.message;button.disabled=false;}else toast(error.message,'er');}
  };
}
