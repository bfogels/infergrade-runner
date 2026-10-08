export function selectableLocalModel(path, discoveredPath = null) {
  return typeof path === 'string' && path.length > 0 && (path.toLowerCase().endsWith('.gguf') || path === discoveredPath);
}
// Local file discovery is diagnostic until an exact artifact is verified.
export function discoveryRows(payload) {
  return (Array.isArray(payload?.files) ? payload.files : []).filter(file =>
    typeof file?.path === 'string' && typeof file?.name === 'string' &&
    Number.isFinite(file?.size_bytes) && file.size_bytes >= 0 && file.read_only === true
  ).slice(0, 500);
}
export function initModelDiscovery({invoke, chooseFolder, useFile, benchmarkFile, formatBytes}) {
  const page=document.querySelector('[data-desktop-view="models"]');if(!page)return;
  const panel=document.createElement('section');panel.className='drawer-panel desktop-discovery';
  panel.innerHTML='<h2 tabindex="-1">Found on this machine</h2><p>Runner finds GGUF files and Safetensors checkpoints in LM Studio, Ollama and the Hugging Face/vLLM cache. Choose a folder to include your own files.</p><p data-discovery-status role="status">Checking local files…</p><div data-discovery-list></div><div data-discovery-folders></div><div class="button-row"><button type="button" class="button-secondary" data-discovery-refresh>Refresh files</button><button type="button" class="button-secondary" data-discovery-add>Add a folder…</button></div>';
  page.insertBefore(panel,page.querySelector('.desktop-models'));
  const status=panel.querySelector('[data-discovery-status]'),list=panel.querySelector('[data-discovery-list]'),folders=panel.querySelector('[data-discovery-folders]');
  let generation=0,pageIndex=0,current=null;
  const render=payload=>{
    current=payload;const files=discoveryRows(payload);list.replaceChildren();folders.replaceChildren();
    status.textContent=files.length?`${files.length} local model${files.length===1?'':'s'} found.`:'No local models found.';
    if(payload.scan_complete===false)status.textContent+=' Scan is partial: some locations are unreadable or the scan limit was reached.';
    pageIndex=Math.min(pageIndex,Math.max(0,Math.ceil(files.length/5)-1));
    for(const file of files.slice(pageIndex*5,pageIndex*5+5)){
      const details=document.createElement('details');details.className='discovered-model';const summary=document.createElement('summary');summary.textContent=`${file.name} · ${formatBytes(file.size_bytes)} · ${file.format==='safetensors'?(file.status==='incomplete'?'Incomplete checkpoint':'Check compatibility'):'GGUF detected'}`;
      const source=document.createElement('p');source.textContent=`${file.source || 'Local folder'} · identity unverified`;
      const path=document.createElement('p');path.className='discovered-path';path.textContent=file.path;
      const notice=document.createElement('p');notice.textContent='GGUF header detected. File name does not verify publisher, quantization, compatibility or memory fit. This local check does not add a point to Compare.';
      if(file.format==='safetensors'){
        notice.textContent=file.reason||'This checkpoint needs a compatibility check and conversion to GGUF before llama.cpp can load it.';
        const instructions=document.createElement('p');instructions.textContent='On Ubuntu, run infergrade models list --converter /path/to/llama.cpp/convert_hf_to_gguf.py to check support. Then explicitly run infergrade models convert --folder with this checkpoint path, --converter with that script and --output with a new .gguf file. Install the converter’s requirements first; conversion may need substantial RAM and disk space. Source files stay unchanged.';
        details.append(summary,source,path,notice,instructions);list.append(details);continue;
      }
      const button=document.createElement('button');button.type='button';button.className='button-secondary';button.textContent='Use for local engine check';button.onclick=()=>useFile(file.path);
      details.append(summary,source,path,notice,button);
      if(benchmarkFile){const benchmark=document.createElement('button');benchmark.type='button';benchmark.className='button-primary';benchmark.textContent='Benchmark privately';benchmark.onclick=()=>benchmarkFile(file.path);details.append(benchmark);}
      list.append(details);
    }
    if(files.length>5){const nav=document.createElement('div');nav.className='button-row';const label=document.createElement('span');label.textContent=`Page ${pageIndex+1} of ${Math.ceil(files.length/5)}`;for(const [text,delta] of [['Previous',-1],['Next',1]]){const b=document.createElement('button');b.type='button';b.className='button-secondary';b.textContent=text;b.disabled=delta<0?pageIndex===0:(pageIndex+1)*5>=files.length;b.onclick=()=>{pageIndex+=delta;render(current);[...list.querySelectorAll('summary,button')].find(e=>!e.disabled)?.focus();};nav.append(b);}nav.append(label);list.append(nav);}
    for(const folder of (Array.isArray(payload.folders)?payload.folders:[]).filter(v=>typeof v==='string').slice(0,16)){
      const row=document.createElement('div');row.className='discovered-folder';const name=document.createElement('span');name.textContent=folder;const button=document.createElement('button');button.type='button';button.className='button-secondary';button.textContent='Stop scanning';button.setAttribute('aria-label',`Stop scanning ${folder}`);button.onclick=()=>request('set_desktop_model_folder',{folder,remove:true});row.append(name,button);folders.append(row);
    }
  };
  const request=async(command,args)=>{
    const own=++generation;for(const b of panel.querySelectorAll('button'))b.disabled=true;status.textContent='Checking local files…';
    try{const call=await invoke();if(!call){if(own===generation){list.replaceChildren();folders.replaceChildren();status.textContent='Open the desktop app to discover local files.';}return;}
      const payload=await call(command,args);if(own===generation){render(payload);if(command==='set_desktop_model_folder')panel.querySelector('h2').focus();}
    }catch{if(own===generation)status.textContent='Could not inspect local files. Check folder access and try again.';}
    finally{if(own===generation){panel.querySelector('[data-discovery-refresh]').disabled=false;panel.querySelector('[data-discovery-add]').disabled=false;}}
  };
  panel.querySelector('[data-discovery-refresh]').onclick=()=>request('desktop_discovered_models');
  panel.querySelector('[data-discovery-add]').onclick=async()=>{try{const folder=await chooseFolder();if(typeof folder==='string')await request('set_desktop_model_folder',{folder,remove:false});}catch{status.textContent='Could not open the folder picker. Try again in the desktop app.';}};
  request('desktop_discovered_models');
}
