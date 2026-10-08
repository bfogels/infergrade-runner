export function createStartupController({read,write,render}) {
 let busy=false,confirmed=null;
 const run=async target=>{
  if(busy)return;
  busy=true;render({state:confirmed,pending:true,error:null});
  try{
   const state=await(target===null?read():write(target));
   if(state?.schema_version!=='infergrade.startup.v1'||typeof state.enabled!=='boolean'||typeof state.available!=='boolean'||!(state.warning===null||typeof state.warning==='string'))throw new Error('Invalid startup response');
   confirmed=state;render({state:confirmed,pending:false,error:null});
  }catch(error){const detail=typeof error==='string'?error:error instanceof Error?error.message:'';const safe=detail.length>0&&detail.length<=512&&!/[\x00-\x1f\x7f-\x9f]/.test(detail)&&detail!=='Invalid startup response';render({state:confirmed,pending:false,error:safe?detail:'Could not confirm the OS login setting. Refresh before trying again.'});}
  finally{busy=false;}
 };
 return{refresh:()=>run(null),setEnabled:enabled=>run(Boolean(enabled))};
}
export function initStartupSettings({invoke}){
 const page=document.querySelector('[data-desktop-view="settings"]');if(!page)return;
 const panel=document.createElement('section');panel.className='drawer-panel desktop-startup';
 panel.innerHTML='<h2>Open at login</h2><label class="background-toggle"><input type="checkbox" aria-label="Open Runner at login" disabled> Open Runner when I sign in</label><p role="status">Checking OS login settings…</p><p class="desktop-sub">This opens the app. Listening still uses your saved pairing and requires an awake machine.</p><button type="button" class="button-secondary">Refresh login setting</button>';
 page.insertBefore(panel,page.querySelector('.desktop-background'));
 const toggle=panel.querySelector('input'),message=panel.querySelector('[role="status"]'),refresh=panel.querySelector('button');
 const call=async(command,args)=>{const transport=await invoke();if(!transport)throw new Error('Desktop only');return transport(command,args);};
 const controller=createStartupController({read:()=>call('desktop_startup_status'),write:enabled=>call('set_desktop_startup',{enabled}),render:({state,pending,error})=>{
  toggle.checked=state?.enabled===true;toggle.disabled=pending||Boolean(error)||state?.available!==true;refresh.disabled=pending;
  panel.setAttribute('aria-busy',String(pending));
  message.textContent=pending?'Confirming OS login settings…':error||state?.warning||(state?.enabled?'Runner will open when you sign in.':'Open at login is off.');
  if(error&&document.activeElement===toggle)refresh.focus();
 }});
 toggle.onchange=()=>controller.setEnabled(toggle.checked);refresh.onclick=()=>controller.refresh();controller.refresh();return controller;
}
