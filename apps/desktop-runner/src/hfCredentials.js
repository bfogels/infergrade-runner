export function hfCredentialSummary(state) {
  if(state?.environment_override) return 'Using a token from this app’s environment. Removing a saved token does not unset it.';
  return state?.saved ? 'A Hugging Face token is saved in this machine’s OS credential store.' : 'No token saved by Runner.';
}
export function initHfCredentials({invoke,openExternal}) {
  const page=document.querySelector('[data-desktop-view="settings"]');if(!page)return;
  const panel=document.createElement('section');panel.className='drawer-panel desktop-hf';
  panel.innerHTML='<h2 tabindex="-1">Hugging Face</h2><p>Only needed for private or gated models. Your token stays on this machine. Accept the model’s license on Hugging Face before downloading.</p><p data-hf-status role="status">Checking saved credential…</p><form data-hf-form><label>Read access token<input type="password" name="token" autocomplete="off" spellcheck="false" maxlength="256" placeholder="hf_…" required></label><div class="button-row"><button type="submit">Verify and save token</button><button type="button" class="button-secondary" data-hf-tokens>Create a read token</button><button type="button" class="button-secondary" data-hf-remove disabled>Remove saved token</button></div></form><p class="desktop-sub">Changes apply when listening next starts. Running jobs keep their current credentials. Runner also reads a personal access token saved by hf auth login.</p>';
  page.insertBefore(panel,page.querySelector('.observed-runtime-surface'));
  const status=panel.querySelector('[data-hf-status]'),input=panel.querySelector('input'),remove=panel.querySelector('[data-hf-remove]');
  let generation=0;
  const request=async(command,args)=>{
    const own=++generation;for(const button of panel.querySelectorAll('button'))button.disabled=true;
    try{const call=await invoke();if(!call){status.textContent='Open the desktop app to manage Hugging Face credentials.';return;}
      const payload=await call(command,args);if(own!==generation)return;
      status.textContent=hfCredentialSummary(payload);remove.dataset.saved=String(payload.saved===true);
      if(command!=='desktop_hf_credential_status')panel.querySelector('h2').focus();
    }catch(error){if(own===generation)status.textContent=typeof error==='string'?error:'Could not change Hugging Face credentials. Try again.';}
    finally{if(own===generation){for(const b of panel.querySelectorAll('button'))b.disabled=false;remove.disabled=remove.dataset.saved!=='true';}}
  };
  panel.querySelector('form').onsubmit=e=>{e.preventDefault();const token=input.value;input.value='';request('save_desktop_hf_credential',{token});};
  remove.onclick=()=>request('clear_desktop_hf_credential');
  panel.querySelector('[data-hf-tokens]').onclick=()=>openExternal('https://huggingface.co/settings/tokens').catch(()=>{status.textContent='Could not open Hugging Face. Visit huggingface.co/settings/tokens.';});
  request('desktop_hf_credential_status');
}
