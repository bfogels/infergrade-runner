import {renderPageComponent} from './desktopNavigation.js';
import {renderNotifications} from './settingViews.js';
export function createFinishNotificationController({read,write,notify,render}){
 let confirmed=null,busy=false,connection='',generation=0,noticeError=null,settingError=null;
 const pending=new Set(),sent=new Set(),deferred=[];
 const show=()=>render({state:confirmed,pending:busy,error:settingError,noticeError});
 const completed=async runId=>{
  if(!connection||!runId)return;
  if(busy){if(deferred.length<32&&!deferred.some(item=>item.runId===runId&&item.generation===generation))deferred.push({runId,generation});return;}
  if(settingError||confirmed?.enabled!==true||confirmed?.available!==true)return;
  const own=generation,key=connection+'|'+runId;if(pending.has(key)||sent.has(key))return;pending.add(key);
  try{const receipt=await notify(runId);if(own!==generation)return;if(receipt?.submitted===true){if(sent.size>=1024)sent.delete(sent.values().next().value);sent.add(key);noticeError=null;}else if(receipt?.submitted!==false)throw new Error();}
  catch{if(own===generation)noticeError='Could not confirm a finish notification. Check your Hub connection and OS notification settings.';}
  finally{pending.delete(key);if(own===generation)show();}
 };
 const run=async target=>{
  if(busy)return;busy=true;settingError=null;show();
  try{const state=await(target===null?read():write(target));if(state?.schema_version!=='infergrade.desktop_notifications.v1'||typeof state.enabled!=='boolean'||typeof state.available!=='boolean'||!(state.warning===null||typeof state.warning==='string'))throw new Error();confirmed=state;}
  catch{settingError='Could not confirm notifications; Retry or turn them off to reset the setting.';}
  finally{busy=false;show();const waiting=deferred.splice(0);for(const item of waiting)if(item.generation===generation)void completed(item.runId);}
 };
 return{refresh:()=>run(null),setEnabled:value=>run(Boolean(value)),setConnectionKey:key=>{if(connection!==key){connection=key;generation++;deferred.length=0;noticeError=null;show();}},completed};
}
export function initFinishNotifications({invoke}){
 const panel=document.querySelector('[data-slot="notifications"]');if(!panel)return null;
 panel.className='setting-row desktop-notifications';
 const emit=state=>renderPageComponent('settings','notifications',state,renderNotifications);
 const call=async(command,args)=>{const native=await invoke();if(!native)throw new Error('Open the desktop app to change this setting.');return native(command,args);};
 const controller=createFinishNotificationController({read:()=>call('desktop_notification_status'),write:enabled=>call('set_desktop_notifications',{enabled}),notify:runId=>call('notify_desktop_run_completed',{runId}),render:emit});
 panel.onchange=event=>{if(event.target.type==='checkbox')controller.setEnabled(event.target.checked);};
 panel.onclick=event=>{if(event.target.matches('[data-retry]'))controller.refresh();if(event.target.matches('[data-off]'))controller.setEnabled(false);};
 window.addEventListener('focus',()=>controller.refresh());
 controller.refresh();return controller;
}
