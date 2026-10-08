export function machineNameController({read,save,apply}) {
  let key='', generation=0, name='', busy=false, error='';
  const emit=()=>apply({key,name,busy,error});
  async function request(label) {
    const own=++generation, owner=key; busy=true;error='';emit();
    try {
      const result=label===undefined?await read():await save(label);
      if(own!==generation||owner!==key)return;
      if(result?.runner_id!==owner.split('|')[0]||typeof result.label!=='string'||!result.label.trim()||[...result.label].length>120||/[\u0000-\u001f\u007f-\u009f]/.test(result.label))throw new Error('The Hub response belongs to a different machine. Refresh.');
      name=result.label;
    } catch(failure) { if(own===generation&&owner===key)error=typeof failure==='string'?failure:failure.message||'Could not read or save the machine name.'; }
    finally {if(own===generation&&owner===key){busy=false;emit();}}
  }
  return {
    setConnectionKey(value){if(value===key)return;key=value||'';++generation;name='';busy=false;error='';emit();if(key)request();},
    refresh(){if(key&&!busy)return request();},
    save(label){if(!key||busy)return;const value=String(label).trim();if(!value||[...value].length>120||/[\u0000-\u001f\u007f-\u009f]/.test(value)){error='Use 1–120 characters without control characters.';emit();return;}return request(value);}
  };
}
export function initMachineSettings({invoke}) {
  const page=document.querySelector('[data-desktop-view="settings"]');if(!page)return null;
  const panel=document.createElement('section');panel.className='drawer-panel desktop-machine-settings';
  panel.innerHTML='<h2>This machine</h2><form><label>Machine name<input type="text" aria-label="Machine name" maxlength="120" autocomplete="off" disabled></label><p class="desktop-sub">Shown in Hub when you choose where to run.</p><div class="button-row"><button type="submit" disabled>Save name</button><button type="button" class="button-secondary" data-name-refresh disabled>Refresh name</button></div><p role="status" data-name-status>Connect this Runner to read its current name.</p></form>';
  page.insertBefore(panel,page.querySelector('.desktop-background')||page.firstElementChild.nextElementSibling);
  const input=panel.querySelector('input'),save=panel.querySelector('[type="submit"]'),refresh=panel.querySelector('[data-name-refresh]'),status=panel.querySelector('[data-name-status]');
  const call=async(command,args)=>{const native=await invoke();if(!native)throw new Error('Open the desktop app to manage its machine name.');return native(command,args);};
  const controller=machineNameController({read:()=>call('desktop_machine_name'),save:label=>call('set_desktop_machine_name',{label}),apply:state=>{
    input.disabled=save.disabled=!state.key||state.busy||!state.name;refresh.disabled=!state.key||state.busy;
    if(!state.busy)input.value=state.name;
    status.textContent=state.error||(state.busy?'Checking the machine name…':state.key?(state.name?'Saved name in Hub.':'Refresh to read the current machine name.'):'Connect this Runner to read its current name.');
    const badge=document.querySelector('.desktop-machine>strong');if(badge)badge.textContent=state.name||'This machine';
  }});
  panel.querySelector('form').onsubmit=event=>{event.preventDefault();controller.save(input.value);};refresh.onclick=()=>controller.refresh();
  document.querySelector('[data-desktop-page="settings"]')?.addEventListener('click',()=>controller.refresh());
  return controller;
}
