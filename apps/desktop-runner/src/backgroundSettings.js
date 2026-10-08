export function listenerEventMatches(event, child) {
  return !event?.listener_pid || !child?.rustManaged || child.pid===event.listener_pid;
}
export function backgroundSummary(state) {
  if(state?.warning)return state.warning;
  if(state?.tray_available!==true)return 'The system tray is unavailable. Keep this window open while Runner works.';
  return state.keep_running===true ? 'Closing this window keeps Runner working in the menu bar or system tray. Use Show Runner to reopen it.' : 'Closing this window quits when Runner is idle. Stop listening or finish the local check before quitting.';
}
export function initBackgroundSettings({invoke,listen,onBlocked}) {
  const page=document.querySelector('[data-desktop-view="settings"]');if(!page)return;
  const panel=document.createElement('section');panel.className='drawer-panel desktop-background';
  panel.innerHTML='<h2 tabindex="-1">Background running</h2><label class="background-toggle"><input type="checkbox" data-keep-running disabled> Keep running when the window is closed</label><p data-background-status role="status">Checking the system tray…</p><p class="desktop-sub">Runner cannot work while this machine is asleep. Quit from the menu bar or system tray after stopping listening.</p>';
  page.insertBefore(panel,page.querySelector('.desktop-hf'));
  const checkbox=panel.querySelector('input'),status=panel.querySelector('[data-background-status]');let last=false,generation=0;
  const request=async(command,args)=>{
    const own=++generation;checkbox.disabled=true;
    try{const call=await invoke();if(!call){status.textContent='Open the desktop app to manage background running.';checkbox.checked=false;return;}
      const state=await call(command,args);if(own!==generation)return;
      last=state.keep_running===true;checkbox.checked=last;checkbox.disabled=state.tray_available!==true;status.textContent=backgroundSummary(state);
    }catch(error){if(own===generation){checkbox.checked=last;checkbox.disabled=false;status.textContent=typeof error==='string'?error:'Could not change background running.';}}
  };
  checkbox.onchange=()=>request('set_desktop_keep_running',{enabled:checkbox.checked});
  const blocked=event=>{status.textContent=event.payload?.message||'Runner is still working. Stop listening or finish the local check before quitting.';onBlocked();panel.querySelector('h2').focus();};
  listen(blocked).catch(()=>{});request('desktop_background_status');
}
