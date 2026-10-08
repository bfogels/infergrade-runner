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
export function initHomeResults({invoke,openResult}){
 const assignment=document.querySelector('[data-assignment-panel]');if(!assignment)return null;
 const panel=document.createElement('section');panel.className='home-accepted-results';panel.hidden=true;panel.setAttribute('aria-label','Accepted results');assignment.append(panel);
 const controller=createHomeResultController({fetchResults:async runId=>{const call=await invoke();if(!call)throw new Error('Desktop only');return call('desktop_run_results',{runId});},render:state=>{
  const focused=document.activeElement?.dataset.homeResultAction;panel.replaceChildren();panel.hidden=!state.runId||!state.connected;if(panel.hidden)return;
  const status=document.createElement('p');status.setAttribute('role','status');status.textContent=state.error?'Could not verify accepted results. Refresh to try again.':state.data?(state.data.results.length?'Hub has accepted the results below.':'No accepted result is linked yet. Open the job to check its status.'):'Check the Hub result before opening your data point.';panel.append(status);
  for(const result of state.data?.results||[]){const row=document.createElement('div');const title=document.createElement('strong');title.textContent=result.title+' · '+result.deployment_profile;row.append(title);
   const detail=document.createElement('p');detail.textContent=result.kind==='report'?'Compare qualification unavailable.':`${(result.score*100).toFixed(1)} / 100 · ${result.seconds_per_task.toFixed(2)} seconds per naturally completed task`;
   row.append(detail);if(result.kind==='compare_context'){const context=document.createElement('p');context.textContent=`${result.qualified_count}/${result.attempted_count} naturally completed tasks. Score keeps the full denominator. This is a context point.`;row.append(context);}
   const action=document.createElement('button');action.type='button';action.className='button-secondary';action.textContent=result.kind==='report'?'Open report':'Show my data point';action.dataset.homeResultAction=result.result_id;action.onclick=()=>{if(!controller.isCurrent(state.runId))return;Promise.resolve(openResult(result,state.data.api_url)).catch(()=>{status.textContent='Could not open the paired Hub. Try again.';});};row.append(action);panel.append(row);
  }
  const refresh=document.createElement('button');refresh.type='button';refresh.className='button-secondary';refresh.textContent=state.error?'Retry results':state.data?'Refresh results':'View results';refresh.dataset.homeResultAction='refresh';refresh.setAttribute('aria-busy',String(state.busy));refresh.onclick=()=>controller.refresh();panel.append(refresh);
  if(focused){const replacement=[...panel.querySelectorAll('button')].find(el=>el.dataset.homeResultAction===focused);(replacement||refresh).focus({preventScroll:true});}
 }});return controller;
}
