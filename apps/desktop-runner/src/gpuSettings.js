const schema='infergrade.cuda_device_policy.v1';
export function gpuSettingsController({read,write,render}){
 let generation=0,busy=false,saved=null,error='';
 const emit=()=>render({saved,pending:busy,error});
 const run=async uuids=>{if(busy)return;const own=++generation;busy=true;error='';emit();try{
  const value=await (uuids===undefined?read():write(uuids));
  if(own!==generation)return;
  if(value?.schema_version!==schema||typeof value.available!=='boolean'||typeof value.selection_ready!=='boolean'||!Array.isArray(value.devices))throw Error();
  saved=value;
 }catch{if(own===generation)error='Could not confirm GPU choice. Refresh or reset the saved preference.';}
 finally{if(own===generation){busy=false;emit();}}};
 return{refresh:()=>run(),select:uuids=>run([...uuids]),reset:()=>run([]),clear:()=>{generation++;busy=false;saved=null;error='';emit();}};
}
export function initGpuSettings({invoke}){
 const page=document.querySelector('[data-desktop-view="settings"]');if(!page)return null;
 const panel=document.createElement('section');panel.className='drawer-panel desktop-gpu-settings';
 panel.innerHTML='<h2 tabindex="-1">GPUs</h2><p class="desktop-sub">Choose physical NVIDIA devices for native llama.cpp. This changes the next benchmark; active work keeps its original choice.</p><div data-gpu-choices role="group" aria-label="GPUs"></div><p class="desktop-sub">Selecting both requests model splitting. Selection does not prove available memory or fit. Execution verifies successful load and observed placement.</p><div class="button-row"><button type="button" class="button-secondary" data-gpu-default>Use runtime default</button><button type="button" class="button-secondary" data-gpu-refresh>Refresh GPUs</button></div><p role="status" data-gpu-status>Checking saved GPU choice…</p>';
 page.append(panel);
 const choices=panel.querySelector('[data-gpu-choices]'),status=panel.querySelector('[data-gpu-status]'),refresh=panel.querySelector('[data-gpu-refresh]'),reset=panel.querySelector('[data-gpu-default]');
 const call=async(command,args)=>{const native=await invoke();if(!native)throw Error();return native(command,args);};
 let selected=[],last=null,restoreFocus=null;
 const focusKey=element=>element?.dataset.gpuUuid?`uuid:${element.dataset.gpuUuid}`:element?.dataset.gpuInput?`input:${element.dataset.gpuInput}`:element?.hasAttribute('data-gpu-both')?'both':element?.hasAttribute('data-gpu-save')?'save':element===refresh?'refresh':element===reset?'reset':null;
 const render=({saved,pending,error})=>{
  const focused=panel.contains(document.activeElement)?focusKey(document.activeElement):null;
  if(focused)restoreFocus=focused;
  reset.disabled=refresh.disabled=pending;panel.setAttribute('aria-busy',String(pending));
  if(saved!==last){last=saved;choices.replaceChildren();selected=saved?.devices.filter(d=>d.selected).map(d=>d.uuid)||[];
   for(const device of saved?.devices||[]){const button=document.createElement('button');button.type='button';button.className='button-secondary';button.textContent=`GPU ${device.index+1} · ${device.model} · ${device.vram_gb} GB`;button.dataset.gpuUuid=device.uuid;button.onclick=()=>controller.select([device.uuid]);choices.append(button);}
   if(saved?.devices.length===2){const both=document.createElement('button');both.type='button';both.className='button-secondary';both.textContent='Both';both.dataset.gpuBoth='';both.onclick=()=>controller.select(saved.devices.map(d=>d.uuid));choices.append(both);}
   if((saved?.devices.length||0)>2){const form=document.createElement('form');for(const device of saved.devices){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=device.uuid;input.dataset.gpuInput=device.uuid;input.checked=device.selected;label.append(input,document.createTextNode(`${device.model} · GPU ${device.index+1}`));form.append(label);}const save=document.createElement('button');save.type='submit';save.dataset.gpuSave='';save.textContent='Save selected GPUs';form.append(save);form.onsubmit=event=>{event.preventDefault();const ids=[...form.querySelectorAll('input:checked')].map(i=>i.value);if(ids.length)controller.select(ids);else status.textContent='Choose a GPU or use runtime default.';};choices.append(form);}
  }
  choices.querySelectorAll('button,input').forEach(control=>control.disabled=pending||!saved?.available||Boolean(error));
  choices.querySelectorAll('[data-gpu-uuid]').forEach(button=>button.setAttribute('aria-pressed',String(saved?.selection_ready&&selected.length===1&&selected[0]===button.dataset.gpuUuid)));
  choices.querySelector('[data-gpu-both]')?.setAttribute('aria-pressed',String(saved?.selection_ready&&selected.length===2));
  status.textContent=pending?'Waiting to confirm the saved GPU choice…':error||saved?.message||(!saved?'Open the desktop app to manage GPUs.':saved.policy?`Saved ${saved.policy.device_count} GPU${saved.policy.device_count===1?'':'s'}. Review the updated choice in Hub before queueing.`:'Runtime default. No physical GPU selection is saved.');
  if(!pending&&restoreFocus){
   const target=[...panel.querySelectorAll('button,input')].find(control=>focusKey(control)===restoreFocus&&!control.disabled)||(error?refresh:panel.querySelector('h2'));
   if(panel.getClientRects().length&&(document.activeElement===document.body||panel.contains(document.activeElement)))target.focus();
   restoreFocus=null;
  }
 };
 const controller=gpuSettingsController({read:()=>call('desktop_gpu_status'),write:uuids=>call('set_desktop_gpu_choice',{uuids}),render});
 refresh.onclick=()=>controller.refresh();reset.onclick=()=>controller.reset();
 document.querySelector('[data-desktop-page="settings"]')?.addEventListener('click',()=>controller.refresh());
 controller.refresh();return controller;
}
