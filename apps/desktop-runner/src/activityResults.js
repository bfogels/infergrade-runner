export function pairedHubRoot(apiUrl){
 const api=new URL(apiUrl);if(api.username||api.password||!/^https?:$/.test(api.protocol))throw new Error('Invalid paired Hub');
 if(api.protocol==='http:'&&!['localhost','127.0.0.1','[::1]'].includes(api.hostname))throw new Error('Hub requires HTTPS');
 return new URL(api.hostname==='api.infergrade.com'?'https://infergrade.com/':api.origin);
}
export function activityResultUrl(apiUrl,resultId,kind){
 if(!/^[-a-zA-Z0-9_]+$/.test(resultId)||!['compare_full','compare_context','report'].includes(kind))throw new Error('Invalid result destination');
 const url=pairedHubRoot(apiUrl);
 if(kind==='report'){url.pathname='/advanced.html';url.searchParams.set('result',resultId);}else{url.pathname='/';url.hash='compare?'+new URLSearchParams({result:resultId});}
 return url.toString();
}
export function createResultLoader({fetchResults,apply,onError}){
 let key='',generation=0;const busy=new Set();
 return {setConnectionKey(next){if(key===next)return;key=next||'';++generation;busy.clear();},
 async load(runId){if(!key||busy.has(runId))return;const own=generation;busy.add(runId);try{const data=await fetchResults(runId);if(own!==generation)return;if(data?.run_id!==runId||!Array.isArray(data.results)||data.results.length>32)throw new Error('Invalid results');apply(runId,data,key);}catch{if(own===generation)onError(runId,key);}finally{if(own===generation)busy.delete(runId);}},
 isCurrent(value){return Boolean(key)&&key===value;}};
}
