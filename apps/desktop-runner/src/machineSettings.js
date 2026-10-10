import {renderPageComponent} from './desktopNavigation.js';
import {renderMachine} from './settingViews.js';
export function machineNameController({read,save,apply}) {
  let key='', generation=0, name='', busy=false, error='';
  const emit=()=>apply({key,name,busy,error});
  async function request(label) {
    const own=++generation, owner=key; busy=true;error='';emit();
    try {
      const result=label===undefined?await read():await save(label);
      if(own!==generation||owner!==key)return;
      if(result?.runner_id!==owner.split('|')[0]||typeof result.label!=='string'||!result.label.trim()||[...result.label].length>120||/[\u0000-\u001f\u007f-\u009f]/.test(result.label))throw new Error('A different machine answered; retry this machine’s connection.');
      name=result.label;
    } catch(failure) { if(own===generation&&owner===key)error=typeof failure==='string'?failure:failure.message||'Could not read or save the machine name.'; }
    finally {if(own===generation&&owner===key){busy=false;emit();}}
  }
  return {
    setConnectionKey(value){if(value===key)return;key=value||'';++generation;name='';busy=false;error='';emit();if(key)request();},
    refresh(){if(key&&!busy)return request();},
    save(label){if(!key||busy)return;const value=String(label).trim();if(!value||[...value].length>120||/[\u0000-\u001f\u007f-\u009f]/.test(value)){error='Use 1–120 characters without control characters.';emit();return;}return request(value);}
  };
}
export function initMachineSettings({invoke}){
 const panel=document.querySelector('[data-slot="machine"]');if(!panel)return null;
 panel.className='setting-row desktop-machine';
 const emit=state=>renderPageComponent('settings','machine',state,renderMachine);
 const call=async(command,args)=>{const native=await invoke();if(!native)throw new Error('Open the desktop app to change this setting.');return native(command,args);};
 const controller=machineNameController({read:()=>call('desktop_machine_name'),save:label=>call('set_desktop_machine_name',{label}),apply:state=>{emit(state);const input=panel.querySelector('input');if(!state.busy)input.value=state.name;document.querySelector('.desktop-machine>strong').textContent=state.name||'This machine';}});
 panel.onchange=event=>{if(event.target.matches('input'))controller.save(event.target.value);};
 panel.onsubmit=event=>{event.preventDefault();controller.save(panel.querySelector('input').value);};
 panel.onclick=event=>{if(event.target.matches('[data-retry]'))controller.refresh();};
 window.addEventListener('focus',()=>controller.refresh());
 return controller;
}
