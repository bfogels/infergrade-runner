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
 const page=document.querySelector('[data-desktop-view="activity"]');if(!page)return null;
 const panel=document.createElement('section');panel.className='drawer-panel desktop-history';panel.innerHTML='<h2 tabindex="-1">Machine activity</h2><p data-activity-status role="status">Connect this Runner to view its Hub jobs.</p><div data-activity-history></div><button type="button" class="button-secondary" data-activity-refresh disabled>Refresh activity</button>';
 page.insertBefore(panel,page.querySelector('.log-disclosure'));
 const status=panel.querySelector('[data-activity-status]'),list=panel.querySelector('[data-activity-history]'),refresh=panel.querySelector('[data-activity-refresh]');
 let resultKey='',lastPayload=null;const resultCache=new Map(),resultErrors=new Set();
 const resultLoader=createResultLoader({fetchResults:async runId=>{const call=await invoke();if(!call)throw new Error('Desktop only');return call('desktop_run_results',{runId});},apply:(id,data,key)=>{resultCache.set(id,data);resultErrors.delete(id);render(lastPayload,key);},onError:(id,key)=>{resultErrors.add(id);render(lastPayload,key);}});
 const render=(payload,key)=>{
  lastPayload=payload;
  if(resultKey!==key){resultKey=key;resultCache.clear();resultErrors.clear();resultLoader.setConnectionKey(key);}

  const focused=document.activeElement,focusedRun=focused?.closest('[data-activity-run-id]')?.dataset.activityRunId,focusedAction=focused?.dataset.activityAction,focusedResult=focused?.dataset.activityResultId;
  list.replaceChildren();refresh.disabled=!key;if(!payload){status.textContent=key?'Open Activity to load this machine’s jobs.':'Connect this Runner to view its Hub jobs.';return;}
  const groups=activityGroups(payload);status.textContent='Most recent 100 jobs assigned to this Runner, including jobs that did not finish. Local engine diagnostics are separate.';
  for(const [group,title] of [['active','Now'],['queued','Up next'],['attention','Needs attention'],['finished','Finished']]){
   const section=document.createElement('section');const heading=document.createElement('h3');heading.textContent=title;section.append(heading);
   if(!groups[group].length){const empty=document.createElement('p');empty.textContent={active:'No benchmark is running.',queued:'Nothing queued for this Runner.',finished:'No finished jobs in this history.',attention:'No paused jobs.'}[group];section.append(empty);}
   for(const run of groups[group]){const article=document.createElement('article');article.className='desktop-history-row';article.dataset.activityRunId=run.run_id;const title=document.createElement('strong');title.textContent=run.model||run.run_id;const detail=document.createElement('p');detail.textContent=activityLabels[run.status]+(run.current_stage?` · ${run.current_stage}`:'')+(run.error_code?` · ${run.error_code}`:'');article.append(title,detail);
    const timestamp=run.updated_at||run.created_at;const when=new Date(timestamp);if(timestamp && Number.isFinite(when.getTime())){const time=document.createElement('time');time.dateTime=when.toISOString();time.textContent=when.toLocaleString();article.append(time);}
    if(run.status==='running' && Number.isFinite(run.progress_percent) && run.progress_percent>=0 && run.progress_percent<=100){const progress=document.createElement('progress');progress.max=100;progress.value=run.progress_percent;progress.setAttribute('aria-label','Runner reported progress');article.append(progress);}
    if(run.publication_state){const visibility=document.createElement('p');visibility.textContent=`Hub visibility: ${run.publication_state.replaceAll('_',' ')}`;article.append(visibility);}
    const button=document.createElement('button');button.type='button';button.className='button-secondary';button.textContent='View job in Hub';button.dataset.activityAction='job';button.onclick=()=>Promise.resolve(openRun(run.run_id,payload.api_url)).catch(()=>{status.textContent='Could not open the paired Hub. Check your browser and try again.';});article.append(button);
    if(run.status==='completed'){
     const results=resultCache.get(run.run_id);
     if(results){
      if(!results.results.length){const message=document.createElement('p');message.textContent='No accepted result is linked to this job yet. View the job in Hub.';article.append(message);}
      for(const result of results.results){const choice=document.createElement('div');const label=document.createElement('p');label.textContent=result.title+' · '+result.deployment_profile+(result.kind==='compare_context'?` · Context only: ${result.qualified_count}/${result.attempted_count} naturally completed tasks. Score keeps the full denominator.`:result.kind==='report'?' · Compare qualification unavailable.':' · Measured result.');choice.append(label);if(result.kind!=='report'){const measured=document.createElement('p');measured.textContent=`${(result.score*100).toFixed(1)} / 100 · ${result.seconds_per_task.toFixed(2)} seconds per naturally completed task`;choice.append(measured);}const action=document.createElement('button');action.type='button';action.className='button-secondary';action.textContent=result.kind==='report'?'Open report':'Show my data point';action.dataset.activityAction=result.kind==='report'?'report':'point';action.dataset.activityResultId=result.result_id;action.onclick=()=>{if(!resultLoader.isCurrent(key))return;Promise.resolve(openResult(result,results.api_url)).catch(()=>{status.textContent='Could not open this result in the paired Hub. Try again.';});};choice.append(action);article.append(choice);}
     }
     const load=document.createElement('button');load.type='button';load.className='button-secondary';load.dataset.activityAction='results';load.textContent=resultErrors.has(run.run_id)?'Retry results':results?'Refresh results':'View results';load.onclick=async()=>{load.setAttribute('aria-busy','true');await resultLoader.load(run.run_id);if(load.isConnected)load.removeAttribute('aria-busy');};article.append(load);
     if(resultErrors.has(run.run_id)){const message=document.createElement('p');message.textContent='Could not load accepted results. Check the connection and try again.';message.setAttribute('role','status');article.append(message);}
    }
    section.append(article);
   }list.append(section);
  }
  if(focusedRun){const row=[...list.querySelectorAll('[data-activity-run-id]')].find(row=>row.dataset.activityRunId===focusedRun);const replacement=row&&[...row.querySelectorAll('button')].find(button=>button.dataset.activityAction===focusedAction&&button.dataset.activityResultId===focusedResult);(replacement||panel.querySelector('h2')).focus({preventScroll:true});}
 };
 const loader=createActivityLoader({fetchActivity:async()=>{const call=await invoke();if(!call)throw new Error('Desktop only');return call('desktop_machine_activity');},render,onError:()=>{status.textContent='Could not refresh machine activity. Check the Hub connection and try again. Existing rows may be out of date.';}});
 refresh.onclick=()=>loader.refresh();new MutationObserver(()=>{if(!page.hidden)loader.refresh();}).observe(page,{attributes:true,attributeFilter:['hidden']});
 setInterval(()=>{if(!page.hidden && !document.hidden)loader.refresh();},15000);return loader;
}
