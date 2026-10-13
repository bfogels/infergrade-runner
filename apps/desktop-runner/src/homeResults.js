import {renderPageComponent} from './desktopNavigation.js';
import {escapeHtml as e} from './desktopViews.js';
export function listenerConnectionMatches(child,key){return Boolean(key)&&child?.connectionKey===key;}
import {createResultLoader} from './activityResults.js';
export function createHomeResultController({fetchResults,render}){
 let connection='',runId='',data=null,error=false,busy=false,generation=0;
 const snapshot=()=>({runId,data,error,busy,connected:Boolean(connection)});
 const loader=createResultLoader({fetchResults,apply:(id,value)=>{if(id!==runId)return;data=value;error=false;render(snapshot());},onError:id=>{if(id!==runId)return;data=null;error=true;render(snapshot());}});
 const reset=()=>{++generation;data=null;error=false;busy=false;loader.setConnectionKey(connection&&runId?`${connection}|${runId}`:'');render(snapshot());};
 return {setConnectionKey(next){if(connection===next)return;connection=next||'';runId='';reset();},setRun(next){if(next===runId)return;runId=/^[-a-zA-Z0-9_]+$/.test(next||'')?next:'';reset();},
 async refresh(){if(!connection||!runId||busy)return;const own=generation,id=runId;busy=true;render(snapshot());await loader.load(id);if(generation===own&&runId===id){busy=false;render(snapshot());}},isCurrent(id){return Boolean(connection)&&runId===id;}};
}

export function renderHomeResults(state={}){
 if(!state.runId||!state.connected)return '<p class="meta">Your accepted results appear here after a benchmark.</p>';
 const rows=state.data?.results||[];
 return `<p class="meta" role="status">${state.error?'Could not read accepted results.':state.busy?'Checking accepted results…':rows.length?'Accepted by Hub.':state.data?'No accepted result is linked yet.':'Checking the result in Hub.'}</p>${rows.map(result=>`<div class="home-result" data-result-id="${e(result.result_id)}"><strong>${e(result.title)} · ${e(result.deployment_profile)}</strong><p>${result.kind==='report'?'Compare qualification unavailable.':`${(result.score*100).toFixed(1)} / 100 · ${result.seconds_per_task.toFixed(2)} s/task`}${result.kind==='compare_context'?` · Context only: ${e(result.qualified_count)}/${e(result.attempted_count)} naturally completed tasks; score keeps the full denominator.`:''}</p><button type="button" data-home-result-action="${e(result.result_id)}">${result.kind==='report'?'Open report':'View in Hub'}</button></div>`).join('')}<button type="button" data-home-result-action="retry" ${state.error?'':'hidden'} ${state.busy?'disabled':''}>Retry results</button>`;
}
export function initHomeResults({invoke,openResult}){
 const panel=document.querySelector('[data-slot="home-results"]');if(!panel)return null;
 panel.className='home-accepted-results';let state={},connection='',generation=0;
 const call=async(command,args)=>{const native=await invoke();if(!native)throw Error();return native(command,args);};
 const controller=createHomeResultController({fetchResults:runId=>call('desktop_run_results',{runId}),render:next=>{state=next;renderPageComponent('home','home-results',state,renderHomeResults);}});
 panel.onclick=async event=>{
  const action=event.target.closest('[data-home-result-action]')?.dataset.homeResultAction;if(!action)return;
  if(action==='retry'){controller.refresh();return;}
  const result=state.data?.results.find(result=>result.result_id===action);
  if(result&&controller.isCurrent(state.runId))try{await openResult(result,state.data.api_url);}catch{renderPageComponent('home','home-results',{...state,error:true},renderHomeResults);}
 };
 renderPageComponent('home','home-results',{connected:false},renderHomeResults);
 return {...controller,setConnectionKey:next=>{
  if(next===connection)return;connection=next;const own=++generation;controller.setConnectionKey(next);
  if(!next)return;
  call('desktop_machine_activity').then(activity=>{
   if(own!==generation||connection!==next||state.runId)return;
   const latest=activity?.runs?.find(run=>run.status==='completed');if(latest){controller.setRun(latest.run_id);controller.refresh();}
  }).catch(()=>{});
 }};
}
