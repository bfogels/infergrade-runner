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
  catch{settingError='Could not confirm the saved notification setting. Refresh, or turn notifications off to reset it.';}
  finally{busy=false;show();const waiting=deferred.splice(0);for(const item of waiting)if(item.generation===generation)void completed(item.runId);}
 };
 return{refresh:()=>run(null),setEnabled:value=>run(Boolean(value)),setConnectionKey:key=>{if(connection!==key){connection=key;generation++;deferred.length=0;noticeError=null;show();}},completed};
}
export function initFinishNotifications({invoke}){
 const settings=document.querySelector('[data-desktop-view="settings"]');if(!settings)return null;
 const panel=document.createElement('section');panel.className='drawer-panel desktop-notifications';panel.innerHTML='<h2>Finish notifications</h2><label class="background-toggle"><input type="checkbox" aria-label="Notify when a benchmark finishes" disabled> Notify me when a benchmark finishes</label><p role="status">Checking saved notification setting…</p><p class="desktop-sub">Notifications use generic text. Open Runner to see the model and results.</p><button type="button" class="button-secondary" data-refresh-notifications>Refresh notification setting</button><button type="button" class="button-secondary" data-reset-notifications>Turn notifications off</button>';
 settings.insertBefore(panel,settings.querySelector('.desktop-hf'));
 const assignment=document.querySelector('[data-assignment-panel]');
 const home=document.createElement('div');home.className='desktop-notification-home';home.innerHTML='<label class="background-toggle"><input type="checkbox" aria-label="Notify me when this benchmark is done" disabled> Notify me when it’s done</label><p role="status"></p>';assignment?.appendChild(home);
 const toggles=[panel.querySelector('input'),home.querySelector('input')],message=panel.querySelector('[role="status"]'),homeMessage=home.querySelector('[role="status"]'),refresh=panel.querySelector('[data-refresh-notifications]'),reset=panel.querySelector('[data-reset-notifications]');
 const call=async(command,args)=>{const transport=await invoke();if(!transport)throw new Error();return transport(command,args);};
 const controller=createFinishNotificationController({read:()=>call('desktop_notification_status'),write:enabled=>call('set_desktop_notifications',{enabled}),notify:runId=>call('notify_desktop_run_completed',{runId}),render:({state,pending,error,noticeError})=>{
  for(const toggle of toggles){toggle.checked=state?.enabled===true;toggle.disabled=pending||Boolean(error)||state?.available!==true;toggle.setAttribute('aria-busy',String(pending));}
  refresh.disabled=pending;reset.disabled=pending;message.textContent=pending?'Confirming saved notification setting…':error||noticeError||state?.warning||(state?.enabled?'Finish notifications enabled.':'Finish notifications are off.');homeMessage.textContent=error||noticeError||state?.warning||'';
 }});
 for(const toggle of toggles)toggle.onchange=()=>controller.setEnabled(toggle.checked);refresh.onclick=()=>controller.refresh();reset.onclick=()=>controller.setEnabled(false);controller.refresh();return controller;
}
