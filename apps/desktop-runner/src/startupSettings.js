import {renderPageComponent} from './desktopNavigation.js';
import {renderStartup} from './settingViews.js';
export function createStartupController({read,write,render}) {
 let busy=false,confirmed=null;
 const run=async target=>{
  if(busy)return;
  busy=true;render({state:confirmed,pending:true,error:null});
  try{
   const state=await(target===null?read():write(target));
   if(state?.schema_version!=='infergrade.startup.v1'||typeof state.enabled!=='boolean'||typeof state.available!=='boolean'||!(state.warning===null||typeof state.warning==='string'))throw new Error('Invalid startup response');
   confirmed=state;render({state:confirmed,pending:false,error:null});
  }catch(error){const detail=typeof error==='string'?error:error instanceof Error?error.message:'';const safe=detail.length>0&&detail.length<=512&&!/[\x00-\x1f\x7f-\x9f]/.test(detail)&&detail!=='Invalid startup response';render({state:confirmed,pending:false,error:safe?detail:'Could not confirm open at login; retry before changing it.'});}
  finally{busy=false;}
 };
 return{refresh:()=>run(null),setEnabled:enabled=>run(Boolean(enabled))};
}
export function initStartupSettings({invoke}){
 const panel=document.querySelector('[data-slot="startup"]');if(!panel)return null;
 panel.className='setting-row desktop-startup';
 const emit=state=>renderPageComponent('settings','startup',state,renderStartup);
 const call=async(command,args)=>{const native=await invoke();if(!native)throw new Error('Open the desktop app to change this setting.');return native(command,args);};
 const controller=createStartupController({read:()=>call('desktop_startup_status'),write:enabled=>call('set_desktop_startup',{enabled}),render:emit});
 panel.onchange=event=>{if(event.target.type==='checkbox')controller.setEnabled(event.target.checked);};
 panel.onclick=event=>{if(event.target.matches('[data-retry]'))controller.refresh();};
 window.addEventListener('focus',()=>controller.refresh());
 controller.refresh();return controller;
}
