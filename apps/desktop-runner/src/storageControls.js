import {renderPageComponent} from './desktopNavigation.js';
import {renderStorage} from './settingViews.js';
const schema='infergrade.cache_budget.v1';
const gib=1024**3;
const limits=[25,50,100,200];
export function storageState(value){
 const keys=['schema_version','limit_gb','limit_bytes','managed_bytes','kept_bytes','reserved_bytes','producer_active','disk_free_bytes','disk_total_bytes'];
 if(!value||Object.keys(value).length!==keys.length||!keys.every(key=>Object.hasOwn(value,key))||value.schema_version!==schema||typeof value.producer_active!=='boolean')throw Error();
 for(const key of ['managed_bytes','kept_bytes','reserved_bytes','disk_free_bytes','disk_total_bytes'])if(!Number.isSafeInteger(value[key])||value[key]<0)throw Error();
 if(value.kept_bytes>value.managed_bytes||value.disk_free_bytes>value.disk_total_bytes||(!value.producer_active&&value.reserved_bytes!==0))throw Error();
 if(value.limit_gb===null?value.limit_bytes!==null:!limits.includes(value.limit_gb)||value.limit_bytes!==value.limit_gb*gib)throw Error();
 return {...value};
}
export function storageController({read,write,confirmTrim,render,confirmed=()=>{}}){
 let generation=0,busy=false,saved=null,error='';
 const emit=()=>render({saved,pending:busy,error});
 const run=async(limit,change=false)=>{
  if(busy||change&&(!saved||error))return;
  if(change&&limit!==null&&!limits.includes(limit))return;
  const own=++generation;busy=true;error='';emit();
  try{
   const trim=change&&limit!==null&&saved.managed_bytes>limit*gib;
   if(trim&&!await confirmTrim(limit)){return;}
   if(own!==generation)return;
   const value=storageState(await(change?write(limit,trim):read()));
   if(own!==generation)return;
   if(change&&value.limit_gb!==limit)throw Error();
   saved=value;
   if(change)confirmed();
  }catch{if(own===generation)error='Could not confirm storage. Refresh before changing the limit. Stop listening and finish active work before trimming.';}
  finally{if(own===generation){busy=false;emit();}}
 };
 return {refresh:()=>run(),setLimit:limit=>run(limit,true),clear:()=>{generation++;busy=false;saved=null;error='';emit();}};
}
export function initStorageControls({invoke,confirmed}){
 const panel=document.querySelector('[data-slot="storage"]');if(!panel)return null;
 panel.className='desktop-storage';
 const call=async(command,args)=>{const native=await invoke();if(!native)throw Error();return native(command,args);};
 const controller=storageController({read:()=>call('desktop_storage_status'),write:(limit,trim)=>call('set_desktop_download_limit',{limitGb:limit,trimOldest:trim}),confirmTrim:limit=>window.confirm(`Lower the download limit to ${limit} GiB? Remove the oldest unkept InferGrade downloads as needed. External files are preserved. Finish current work first.`),render:state=>{renderPageComponent('models','storage',state,renderStorage);const select=panel.querySelector('select');select.value=state.saved?state.saved.limit_gb===null?'none':String(state.saved.limit_gb):'unknown';},confirmed});
 panel.onchange=event=>{if(event.target.matches('select'))controller.setLimit(event.target.value==='none'?null:Number(event.target.value));};
 panel.onclick=event=>{if(event.target.matches('[data-retry]'))controller.refresh();};
 document.querySelector('[data-desktop-page="models"]')?.addEventListener('click',()=>controller.refresh());window.addEventListener('focus',()=>controller.refresh());controller.refresh();return controller;
}
