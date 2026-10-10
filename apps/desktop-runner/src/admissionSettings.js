import {renderPageComponent} from './desktopNavigation.js';
import {renderAdmission} from './settingViews.js';
export function createAdmissionController({read,write,render}) {
 let generation=0,busy=false,confirmed=null;
 const run=async target=>{if(busy){render({paused:confirmed,pending:true,error:null});return;}const own=++generation;busy=true;render({paused:confirmed,pending:true,error:null});try{const state=await (target===null?read():write(target));if(own!==generation)return;if(state?.schema_version!=='infergrade.admission.v1'||typeof state.paused!=='boolean')throw new Error('Invalid admission response');confirmed=state.paused;render({paused:confirmed,pending:false,error:null});}catch{if(own===generation)render({paused:confirmed,pending:false,error:'Could not confirm the pause setting; retry before changing it.'});}finally{if(own===generation)busy=false;}};
 return{refresh:()=>run(null),setPaused:value=>run(value),clear:()=>{generation++;busy=false;confirmed=null;render({paused:null,pending:false,error:null});}};
}
export function initAdmissionSettings({invoke,onState}){
 const panel=document.querySelector('[data-slot="admission"]');if(!panel)return null;
 panel.className='setting-row desktop-admission';
 const emit=state=>renderPageComponent('home','admission',state,renderAdmission);
 const call=async(command,args)=>{const native=await invoke();if(!native)throw new Error('Open the desktop app to change this setting.');return native(command,args);};
 const controller=createAdmissionController({read:()=>call('desktop_admission_status'),write:paused=>call('set_desktop_admission_paused',{paused}),render:state=>{emit(state);onState(state);}});
 panel.onchange=event=>{if(event.target.type==='checkbox')controller.setPaused(event.target.checked);};
 panel.onclick=event=>{if(event.target.matches('[data-retry]'))controller.refresh();};
 window.addEventListener('focus',()=>controller.refresh());
 controller.refresh();return controller;
}
