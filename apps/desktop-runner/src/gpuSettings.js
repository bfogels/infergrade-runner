import {renderPageComponent} from './desktopNavigation.js';
import {renderGpu} from './settingViews.js';
const schema='infergrade.cuda_device_policy.v1';
export function gpuSettingsController({read,write,render}){
 let generation=0,busy=false,saved=null,error='';
 const emit=()=>render({saved,pending:busy,error});
 const run=async uuids=>{if(busy)return;const own=++generation;busy=true;error='';emit();try{
  const value=await (uuids===undefined?read():write(uuids));
  if(own!==generation)return;
  if(value?.schema_version!==schema||typeof value.available!=='boolean'||typeof value.selection_ready!=='boolean'||!Array.isArray(value.devices))throw Error();
  saved=value;
 }catch{if(own===generation)error='Could not confirm GPU choice; retry or choose Default to reset it.';}
 finally{if(own===generation){busy=false;emit();}}};
 return{refresh:()=>run(),select:uuids=>run([...uuids]),reset:()=>run([]),clear:()=>{generation++;busy=false;saved=null;error='';emit();}};
}
export function initGpuSettings({invoke}){
 const panel=document.querySelector('[data-slot="gpu"]');if(!panel)return null;
 panel.className='setting-row desktop-gpu';
 const emit=state=>renderPageComponent('settings','gpu',state,renderGpu);
 const call=async(command,args)=>{const native=await invoke();if(!native)throw new Error('Open the desktop app to change this setting.');return native(command,args);};
 let saved=null,draft=false;
 const controller=gpuSettingsController({read:()=>call('desktop_gpu_status'),write:uuids=>call('set_desktop_gpu_choice',{uuids}),render:state=>{saved=state.saved;emit(state);}});
 panel.onclick=event=>{const button=event.target.closest('button');if(!button||button.disabled)return;if(button.matches('[data-retry]'))controller.refresh();else if(button.matches('[data-gpu-default]'))controller.reset();else if(button.matches('[data-gpu-both]'))controller.select(saved.devices.map(d=>d.uuid));else if(button.dataset.gpuUuid)controller.select([button.dataset.gpuUuid]);};
 panel.onchange=()=>{draft=true;};
 panel.onsubmit=event=>{event.preventDefault();draft=false;controller.select([...panel.querySelectorAll('input:checked')].map(input=>input.value));};
 window.addEventListener('focus',()=>{if(!draft)controller.refresh();});
 controller.refresh();return controller;
}
