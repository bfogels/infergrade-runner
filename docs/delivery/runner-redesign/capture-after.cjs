async (page)=>{
 const out='/Users/brianfogelson/Desktop/Code/infergrade/docs/delivery/runner-redesign';
 const errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
 await page.addInitScript(()=>{
  const scenario=new URL(location.href).searchParams.get('scenario')||'first-launch';
  localStorage.setItem('infergrade.runner.theme','light');
  const paired=scenario!=='first-launch';let paused=false,startup=true,notifications=true,background=true;
  const callbacks=new Map(),events=new Map();let sequence=1;
  window.fixtureEvent=(name,payload)=>callbacks.get(events.get(name))?.({event:name,id:1,payload});
  const api='https://api.infergrade.com/';
  const runs=paired?[{run_id:'run_fixture_qwen',status:'completed',model:'Qwen3.5 4B · Q4_K_M',created_at:'2026-10-10T13:00:00Z',updated_at:'2026-10-10T13:07:00Z'}]:[];
  const artifacts=[{name:'Qwen3.5-4B-Q4_K_M.gguf',artifact_id:'artifact_fixture',managed:true,keep:false,size_bytes:2800000000,quantization:'Q4_K_M',last_used_at:'2026-10-10T13:00:00Z'}];
  window.fixtureCalls=[];
  window.__TAURI_INTERNALS__={transformCallback:fn=>{const id=sequence++;callbacks.set(id,fn);return id;},unregisterCallback:id=>callbacks.delete(id),invoke:async(command,args={})=>{
   window.fixtureCalls.push({command,args});
   if(command==='plugin:event|listen'){events.set(args.event,args.handler);return sequence++;}
   if(command==='plugin:event|unlisten')return;
   if(command==='plugin:app|version')return '0.3.70';
   if(command==='plugin:deep-link|get_current')return [];
   if(command==='plugin:shell|open')return;
   if(command==='runner_pairing_status')return {token:{status:paired?'present':'missing'},profile:{status:paired?'present':'missing',profile:{runner_id:'runner_fixture',api_url:api,label:'This Mac'}}};
   if(command==='desktop_sidecar_diagnostic')return {code:0,stderr:'',stdout:args.args[0]==='desktop-readiness'?JSON.stringify({status:'ok',hardware_class:'apple_silicon',llama_cpp_runtime:'available',llama_cpp_message:'Runtime ready.',native_benchmark_message:'Ready.',docker:{status:'missing'},podman:{status:'missing'}}):'InferGrade Runner 0.3.70'};
   if(command==='refresh_desktop_runtime_catalog')return {entries:[],status:'available'};
   if(command==='llama_cpp_runtime_plan')return {native_runtime_status:'available',selected_runtime:{status:'selected'},managed_runtimes:[]};
   if(command==='desktop_model_cache_status')return {artifacts,artifact_count:artifacts.length,artifact_bytes:2800000000};
   if(command==='set_desktop_model_keep'){artifacts[0].keep=args.keep;return {artifacts,artifact_count:1,artifact_bytes:2800000000};}
   if(command==='clear_desktop_model_cache')return {status:{artifacts:[],artifact_count:0,artifact_bytes:0}};
   if(command==='desktop_discovered_models')return {scan_complete:true,folders:[],files:[{name:'Llama-3.2-3B-Q4_K_M.gguf',path:'/fixture/Llama-3.2-3B-Q4_K_M.gguf',source:'LM Studio',format:'gguf',size_bytes:2000000000,read_only:true}]};
   if(command==='desktop_machine_activity')return {api_url:api,runs};
   if(command==='desktop_run_results')return {api_url:api,run_id:args.runId,results:[{result_id:'result_fixture',kind:'compare_full',title:'Qwen3.5 4B',deployment_profile:'Chat & reasoning',score:.71,seconds_per_task:3.2}]};
   if(command==='desktop_private_benchmark_status')return window.fixturePrivateStatus||{status:'idle',pid:null};
   if(command==='start_desktop_private_benchmark'){window.fixturePrivateStatus={status:'running',pid:43,phase:'Checking local tasks'};return window.fixturePrivateStatus;}
   if(command==='desktop_private_benchmark_history')return {schema_version:'infergrade.private_history.v1',results:[],unreadable_count:0};
   if(command==='desktop_hf_credential_status')return {saved:scenario!=='needs-hf-token',environment_override:false};
   if(command==='desktop_background_status'||command==='set_desktop_keep_running'){if(args.enabled!==undefined)background=args.enabled;return {keep_running:background,tray_available:true,warning:null};}
   if(command==='desktop_startup_status'||command==='set_desktop_startup'){if(args.enabled!==undefined)startup=args.enabled;return {schema_version:'infergrade.startup.v1',enabled:startup,available:true,warning:null};}
   if(command==='desktop_notification_status'||command==='set_desktop_notifications'){if(args.enabled!==undefined)notifications=args.enabled;return {schema_version:'infergrade.desktop_notifications.v1',enabled:notifications,available:true,warning:null};}
   if(command==='desktop_machine_name'||command==='set_desktop_machine_name')return {runner_id:'runner_fixture',label:args.label||'This Mac'};
   if(command==='desktop_gpu_status')return {schema_version:'infergrade.cuda_device_policy.v1',available:false,selection_ready:false,policy:null,devices:[]};
   if(command==='desktop_storage_status')return {schema_version:'infergrade.cache_budget.v1',limit_gb:50,limit_bytes:50*1024**3,managed_bytes:2800000000,kept_bytes:0,reserved_bytes:0,producer_active:false,disk_free_bytes:scenario==='low-disk'?500000000:120000000000,disk_total_bytes:512000000000};
   if(command==='desktop_admission_status'||command==='set_desktop_admission_paused'){if(args.paused!==undefined)paused=args.paused;return {schema_version:'infergrade.admission.v1',paused};}
   if(command==='worker_protocol_ping'){if(scenario==='offline')throw Error('Hub unavailable');return {status:'sent',runner_id:'runner_fixture'};}
   if(command==='start_runner_listener')return {pid:42,plan:{runner_id:'runner_fixture',execution_mode:'local_native',credential_source:'os_keyring'}};
   if(command==='notify_desktop_run_completed')return {submitted:true};
   if(command==='stop_runner_listener')return {};
   throw Error('Unmocked command: '+command);
  }};
  window.__TAURI_EVENT_PLUGIN_INTERNALS__={unregisterListener:()=>{}};
 });
 await page.setViewportSize({width:1000,height:700});
 const scenarios=[];
 for(const scenario of ['first-launch','ready','running','finished','failed','offline','low-disk','needs-hf-token','paired-idle']){
  await page.goto('http://127.0.0.1:1420/?scenario='+scenario);
  await page.getByRole('heading',{name:scenario==='first-launch'?'Connect this machine':'Needs attention',exact:true}).waitFor();
  if(scenario!=='first-launch'){
   await page.getByRole('button',{name:'Settings',exact:true}).click();
   await page.locator('[data-support-details]').evaluate(node=>node.open=true);
   await page.getByRole('button',{name:'Home',exact:true}).click();
   await page.locator('[data-home-primary]').click();
   await page.getByRole('button',{name:'Settings',exact:true}).click();
   await page.waitForTimeout(100);
   if(!['paired-idle','offline'].includes(scenario))await page.locator('[data-start-runner]').click();
   await page.getByRole('button',{name:'Home',exact:true}).click();
   if(['running','finished','failed','low-disk','needs-hf-token'].includes(scenario)){
    await page.evaluate(s=>window.fixtureEvent('runner-listener-event',{type:'assignment_update',listener_pid:42,run_id:'run_fixture_qwen',title:'Qwen3.5 4B · Chat & reasoning',phase:s==='finished'?'Complete':['failed','low-disk','needs-hf-token'].includes(s)?'Needs attention':'Running',progress:s==='running'?48:100,result_id:s==='finished'?'result_fixture':'',description:s==='low-disk'?'Disk space is low.':s==='needs-hf-token'?'Hugging Face token required.':s==='failed'?'The model could not load.':'Benchmark tasks are running on this machine.'}),scenario);
   }
  }
  await page.screenshot({path:out+'/after-'+scenario+'.png'});
  await page.addScriptTag({path:'/tmp/runner-redesign-a11y/node_modules/axe-core/axe.min.js'});
  const accessibility=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
  scenarios.push({scenario,heading:await page.locator('[data-primary-state-title]').innerText(),violations:accessibility.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))});
 }
 await page.getByRole('button',{name:'Settings',exact:true}).click();await page.locator('[data-support-details]').evaluate(node=>node.open=false);await page.screenshot({path:out+'/after-settings.png'});
 await page.getByRole('button',{name:'Models',exact:true}).click();await page.screenshot({path:out+'/after-models.png'});
 await page.getByRole('button',{name:'Activity',exact:true}).click();await page.screenshot({path:out+'/after-activity.png'});
 return {errors,scenarios};
}
