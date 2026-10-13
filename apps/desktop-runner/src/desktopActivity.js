import {renderPageComponent} from './desktopNavigation.js';
import {renderActivityList} from './activityView.js';
import {pairedHubRoot,createResultLoader} from './activityResults.js';
export function activityRunUrl(apiUrl,runId){
 if(!/^[-a-zA-Z0-9_]+$/.test(runId))throw new Error('Invalid paired Hub job link');
 const url=pairedHubRoot(apiUrl);url.pathname='/runs';url.searchParams.set('run',runId);return url.toString();
}
export const activityLabels={awaiting_execution:'Waiting for this Runner',queued:'Queued',dispatching:'Starting',running:'Running',completed:'Completed',failed:'Failed',cancelled:'Cancelled',paused:'Paused'};
export function activityGroups(payload){
  const rows=(Array.isArray(payload?.runs)?payload.runs:[]).filter(r=>typeof r?.run_id==='string' && Object.hasOwn(activityLabels,r.status)).slice(0,100);
  return {attention:rows.filter(r=>r.status==='paused'),active:rows.filter(r=>r.status==='running'),queued:rows.filter(r=>['awaiting_execution','queued','dispatching'].includes(r.status)),finished:rows.filter(r=>['completed','failed','cancelled'].includes(r.status))};
}
export function createActivityLoader({fetchActivity,render,onError}){
 let key='',generation=0,inFlight=false;
 return {
  setConnectionKey(next){if(next===key)return;key=next;generation++;inFlight=false;render(null,key);},
  async refresh(){if(!key || inFlight)return;inFlight=true;const own=generation;try{const payload=await fetchActivity();if(own===generation)render(payload,key);}catch{if(own===generation)onError();}finally{if(own===generation)inFlight=false;}}
 };
}
export function initDesktopActivity({invoke,openRun,openResult}){
 const panel=document.querySelector('[data-slot="activity"]');if(!panel)return null;
 panel.className='desktop-history';let state={key:'',payload:null,results:{},errors:{}};
 const show=()=>renderPageComponent('activity','activity',state,renderActivityList);
 const call=async(command,args)=>{const native=await invoke();if(!native)throw Error();return native(command,args);};
 const resultLoader=createResultLoader({fetchResults:runId=>call('desktop_run_results',{runId}),apply:(id,data,key)=>{if(key!==state.key)return;state={...state,results:{...state.results,[id]:data},errors:{...state.errors,[id]:false}};show();},onError:(id,key)=>{if(key!==state.key)return;state={...state,errors:{...state.errors,[id]:true}};show();}});
 const loader=createActivityLoader({fetchActivity:()=>call('desktop_machine_activity'),render:(payload,key)=>{if(key!==state.key){resultLoader.setConnectionKey(key);state={key,payload,results:{},errors:{}};}else state={...state,payload,error:null};show();},onError:()=>{state={...state,error:true};show();}});
 panel.onclick=async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.matches('[data-activity-retry]')){loader.refresh();return;}
  const runId=button.closest('[data-activity-run-id]')?.dataset.activityRunId;if(!runId)return;
  try{
   if(button.dataset.activityAction==='results'){button.disabled=true;await resultLoader.load(runId);button.disabled=false;}
   else if(button.dataset.activityAction==='result'){const data=state.results[runId],result=data?.results.find(result=>result.result_id===button.dataset.activityResultId);if(result&&resultLoader.isCurrent(state.key))await openResult(result,data.api_url);}
   else await openRun(runId,state.payload.api_url);
  }catch{state={...state,error:true};show();}
 };
 const page=panel.closest('[data-desktop-view]');
 new MutationObserver(()=>{if(!page.hidden)loader.refresh();}).observe(page,{attributes:true,attributeFilter:['hidden']});
 window.addEventListener('focus',()=>{if(!page.hidden)loader.refresh();});
 setInterval(()=>{if(!page.hidden&&!document.hidden)loader.refresh();},15000);show();return loader;
}
