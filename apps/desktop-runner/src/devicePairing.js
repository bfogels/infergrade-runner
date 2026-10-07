// Only the native process holds device and runner credentials.
export function devicePairingController({invoke,openExternal,onIssued,onStatus,onPaired,onActive,onStopped,onCompleting}) {
  let generation=0,active=false,completing=false,issued=null,timer=null,wake=null;
  const pause=ms=>new Promise(resolve=>{wake=resolve;timer=setTimeout(()=>{timer=null;wake=null;resolve();},ms);});
  async function cancel(){
    if(completing)return;
    generation++; if(timer)clearTimeout(timer);timer=null;wake?.();wake=null;
    await invoke('cancel_runner_device_pairing');active=false;issued=null;onActive(false);await onStopped?.();
  }
  async function open(){if(issued)await openExternal(issued.verification_uri);}
  async function start(apiUrl,label){
    if(active)return;
    const current=++generation;active=true;onActive(true);onStatus('Starting connection…');
    try{
      const response=await invoke('begin_runner_device_pairing',{apiUrl,label:label||null});
      if(current!==generation)return;
      issued=response;onIssued(response);onStatus('Approve this code in your browser.');
      try{await open();}catch{onStatus('Open the connection page below to approve this code.');}
      let interval=response.interval;
      const deadline=Date.now()+response.expires_in*1000;
      while(current===generation&&Date.now()<deadline){
        await pause(Math.max(1,Math.min(60,interval))*1000);
        if(current!==generation)return;
        if(Date.now()>=deadline)break;
        let result;
        try{result=await invoke('poll_runner_device_pairing',{sessionId:response.session_id});}
        catch(error){if(current!==generation)return;onStatus(String(error?.message||error));continue;}
        if(current!==generation)return;
        if(result.status==='paired'){completing=true;issued=null;onCompleting?.(true);await onPaired(result.pairing);return;}
        if(result.status==='denied'){onStatus('Connection declined. Start again when you are ready.');return;}
        if(result.status==='canceled'){onStatus('This connection stopped. Start again.');return;}
        if(result.status==='expired'){onStatus('This code expired. Start again for a new code.');return;}
        if(result.status!=='pending')throw new Error('Hub returned an unexpected connection status.');
        interval=result.interval||interval;
        onStatus('Approve this code in your browser.');
      }
      if(current===generation)onStatus('This code expired. Start again for a new code.');
    }catch(error){if(current===generation)onStatus(String(error?.message||error));}
    finally{if(current===generation){await invoke('cancel_runner_device_pairing').catch(()=>{});active=false;issued=null;completing=false;onCompleting?.(false);onActive(false);}}
  }
  return {start,cancel,open,isActive:()=>active};
}
