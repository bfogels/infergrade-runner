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
 const page=document.querySelector('[data-desktop-view="models"]');if(!page)return null;
 const panel=document.createElement('section');panel.className='drawer-panel desktop-storage';
 panel.innerHTML='<h2 tabindex="-1">Storage</h2><div class="storage-summary"><strong data-storage-owned>Downloads unavailable</strong><span data-storage-free>Disk space unavailable</span></div><meter data-storage-meter min="0" max="1" value="0" aria-label="Owned downloads as a proportion of the saved limit" hidden></meter><p class="desktop-sub" data-storage-details>Open the desktop app to inspect storage.</p><div class="button-row compact-actions"><label>Keep downloads under <select aria-label="Download size limit" data-storage-limit disabled><option value="unknown">Unavailable</option><option value="25">25 GiB</option><option value="50">50 GiB</option><option value="100">100 GiB</option><option value="200">200 GiB</option><option value="none">No limit</option></select></label><button type="button" class="button-secondary" data-storage-refresh>Refresh storage</button></div><p class="desktop-sub">Lowering the limit can clear the oldest unkept downloads with your confirmation. New downloads stop at the cap. Kept, legacy and external files are preserved.</p><p class="desktop-sub" data-storage-status role="status"></p>';
 const downloads=page.querySelector('.desktop-models');if(downloads)downloads.after(panel);else page.append(panel);
 const select=panel.querySelector('[data-storage-limit]'),refresh=panel.querySelector('[data-storage-refresh]'),meter=panel.querySelector('meter');
 const format=bytes=>`${(bytes/gib).toLocaleString(undefined,{maximumFractionDigits:1})} GiB`;
 let restoreFocus=null;
 const render=({saved,pending,error})=>{
  if(panel.contains(document.activeElement)&&[select,refresh].includes(document.activeElement))restoreFocus=document.activeElement;
  panel.setAttribute('aria-busy',String(pending));refresh.disabled=pending;select.disabled=pending||!saved||Boolean(error);
  select.value=saved?saved.limit_gb===null?'none':String(saved.limit_gb):'unknown';select.querySelector('[value="unknown"]').hidden=Boolean(saved);
  panel.querySelector('[data-storage-owned]').textContent=saved?`${format(saved.managed_bytes)} in InferGrade downloads`:'Downloads unavailable';
  panel.querySelector('[data-storage-free]').textContent=saved?`${format(saved.disk_free_bytes)} free on disk`:'Disk space unavailable';
  panel.querySelector('[data-storage-details]').textContent=saved?`${format(saved.kept_bytes)} kept · ${format(saved.reserved_bytes)} reserved${saved.producer_active?' · Download in progress':''} · ${format(saved.disk_total_bytes)} disk capacity`:'Storage has not been confirmed.';
  meter.hidden=!saved||saved.limit_gb===null;meter.value=saved?.limit_bytes?Math.min(1,saved.managed_bytes/saved.limit_bytes):0;
  panel.querySelector('[data-storage-status]').textContent=pending?'Checking saved storage…':error||(!saved?'Open the desktop app to inspect storage.':saved.limit_gb===null?'No download limit is saved.':`Saved limit: ${saved.limit_gb} GiB.`);
  if(!pending&&restoreFocus){if(panel.getClientRects().length&&(document.activeElement===document.body||panel.contains(document.activeElement)))(error?refresh:restoreFocus).focus();restoreFocus=null;}
 };
 const call=async(command,args)=>{const native=await invoke();if(!native)throw Error();return native(command,args);};
 const controller=storageController({read:()=>call('desktop_storage_status'),write:(limit,trim)=>call('set_desktop_download_limit',{limitGb:limit,trimOldest:trim}),confirmTrim:limit=>window.confirm(`Lower the download limit to ${limit} GiB? Remove the oldest eligible unkept downloads as needed. Kept, legacy and external files are preserved. Stop listening and finish active work first.`),render,confirmed});
 select.onchange=()=>controller.setLimit(select.value==='none'?null:Number(select.value));refresh.onclick=()=>controller.refresh();
 document.querySelector('[data-desktop-page="models"]')?.addEventListener('click',()=>controller.refresh());controller.refresh();return controller;
}
