export function createAdmissionController({read,write,render}) {
 let generation=0,busy=false,confirmed=null;
 const run=async target=>{if(busy){render({paused:confirmed,pending:true,error:null});return;}const own=++generation;busy=true;render({paused:confirmed,pending:true,error:null});try{const state=await (target===null?read():write(target));if(own!==generation)return;if(state?.schema_version!=='infergrade.admission.v1'||typeof state.paused!=='boolean')throw new Error('Invalid admission response');confirmed=state.paused;render({paused:confirmed,pending:false,error:null});}catch{if(own===generation)render({paused:confirmed,pending:false,error:'Could not confirm saved admission state. Refresh before trying again.'});}finally{if(own===generation)busy=false;}};
 return{refresh:()=>run(null),setPaused:value=>run(value),clear:()=>{generation++;busy=false;confirmed=null;render({paused:null,pending:false,error:null});}};
}
export function initAdmissionSettings({invoke,onState}){
 const home=document.querySelector('[data-desktop-view="home"]');if(!home)return null;
 const panel=document.createElement('section');panel.className='drawer-panel desktop-admission';panel.innerHTML='<h2>New benchmarks</h2><label class="background-toggle"><input type="checkbox" aria-label="Pause new benchmarks" disabled> Pause new benchmarks</label><p role="status" data-admission-status>Checking saved admission state…</p><p class="desktop-sub">Any active benchmark continues. Queued work keeps its place.</p><button type="button" class="button-secondary" data-admission-refresh>Refresh saved state</button>';
 home.insertBefore(panel,home.querySelector('.listener-surface'));
 const toggle=panel.querySelector('input'),status=panel.querySelector('[data-admission-status]'),refresh=panel.querySelector('button');
 let unknown=true;
 const render=state=>{unknown=state.paused===null;toggle.checked=state.paused===true;toggle.disabled=unknown||Boolean(state.error);toggle.setAttribute('aria-busy',String(state.pending));refresh.setAttribute('aria-busy',String(state.pending));status.textContent=state.pending?'Waiting to confirm admission. Current work continues…':state.error|| (unknown?'Open the desktop app to manage admission.':state.paused?'Paused: this machine will not claim new benchmarks.':'New benchmarks enabled.');onState(state);if(state.error&&document.activeElement===toggle)refresh.focus();};
 const call=async(command,args)=>{const transport=await invoke();if(!transport)throw new Error('Desktop only');return transport(command,args);};
 const controller=createAdmissionController({read:()=>call('desktop_admission_status'),write:paused=>call('set_desktop_admission_paused',{paused}),render});
 toggle.onchange=()=>{if(!unknown)controller.setPaused(toggle.checked);};refresh.onclick=()=>controller.refresh();controller.refresh();return controller;
}
