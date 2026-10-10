import {renderPageComponent} from './desktopNavigation.js';
import {renderBackground} from './settingViews.js';
export function listenerEventMatches(event, child) {
  return !event?.listener_pid || !child?.rustManaged || child.pid===event.listener_pid;
}
export function backgroundSummary(state) {
  if(state?.warning)return state.warning;
  if(state?.tray_available!==true)return 'The system tray is unavailable. Keep this window open while Runner works.';
  return state.keep_running===true ? 'Closing this window keeps Runner working in the menu bar or system tray. Use Show Runner to reopen it.' : 'Closing this window quits when Runner is idle. Stop listening or finish the local check before quitting.';
}
export function initBackgroundSettings({invoke,listen,onBlocked}) {
 const panel=document.querySelector('[data-slot="background"]');if(!panel)return;
 panel.className='setting-row desktop-background';let saved=null,busy=false;
 const request=async(enabled)=>{if(busy)return;busy=true;renderPageComponent('settings','background',{state:saved,pending:true},renderBackground);
 try{const native=await invoke();if(!native)throw Error();saved=await native(enabled===undefined?'desktop_background_status':'set_desktop_keep_running',enabled===undefined?undefined:{enabled});renderPageComponent('settings','background',{state:saved},renderBackground);}
 catch{renderPageComponent('settings','background',{state:saved,error:'Could not confirm background running.'},renderBackground);}
 finally{busy=false;}};
 panel.onchange=event=>{if(event.target.type==='checkbox')request(event.target.checked);};panel.onclick=event=>{if(event.target.matches('[data-retry]'))request();};
 listen(event=>{renderPageComponent('settings','background',{state:saved,error:event.payload?.message||'Finish current work before quitting.'},renderBackground);onBlocked();panel.querySelector('h2').focus();}).catch(()=>{});
 window.addEventListener('focus',()=>request());request();return {refresh:()=>request()};
}
