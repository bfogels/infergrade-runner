// Move the existing controls into the approved four-page shell. Their native
// event handlers and state nodes remain the same DOM objects.
let pages=null;
export function showDesktopPage(id,{focus=true}={}){
  if(!pages?.has(id))return;
  for(const [name,page] of pages){page.hidden=name!==id;}
  for(const button of document.querySelectorAll('[data-desktop-page]')){
    if(button.dataset.desktopPage===id)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  if(focus)[...pages.get(id).querySelectorAll('h1,h2,h3')].find(node=>node.getClientRects().length)?.focus({preventScroll:true});
  document.querySelector('[data-desktop-content]')?.scrollTo(0,0);
}
export function initDesktopNavigation(){
  const frame=document.querySelector('.app-frame');if(!frame)return;
  const sidebar=document.createElement('aside');sidebar.className='desktop-side';
  sidebar.innerHTML='<a class="desktop-brand" href="#home"><span>IG</span>InferGrade Runner</a><nav aria-label="Runner">'+[['home','Home'],['models','Models'],['activity','Activity'],['settings','Settings']].map(([id,label])=>`<button type="button" data-desktop-page="${id}">${label}</button>`).join('')+'</nav><div class="desktop-machine"><strong>This machine</strong><div data-desktop-status></div><p>Manage listening from Home.</p></div>';
  const content=document.createElement('div');content.dataset.desktopContent='';
  pages=new Map(['home','models','activity','settings'].map(id=>{
    const section=document.createElement('section');section.className='desktop-page';section.dataset.desktopView=id;
    section.innerHTML=id==='home'?'':`<h1 tabindex="-1">${id[0].toUpperCase()+id.slice(1)}</h1><p class="desktop-sub">${({models:'Local model files and the native starter check.',activity:'Current assignment and listener output.',settings:'Connection, engine, updates and support.'})[id]}</p>`;
    content.append(section);return [id,section];
  }));
  const move=(selector,id)=>{const node=frame.querySelector(selector);if(node)pages.get(id).append(node);};
  const welcome=document.createElement('section');welcome.className='desktop-welcome';welcome.innerHTML='<h1 tabindex="-1">Benchmark models on this machine.</h1><p>Connect to your account, choose a model in Hub, and measure how it runs here.</p><button type="button" data-shell-connect>Connect to InferGrade</button><button type="button" class="button-secondary" data-shell-models>View local model controls</button>';pages.get('home').append(welcome);welcome.querySelector('[data-shell-connect]').onclick=()=>showDesktopPage('settings');welcome.querySelector('[data-shell-models]').onclick=()=>showDesktopPage('models');
  move('.primary-surface','home');move('.pairing-surface','settings');move('.listener-surface','home');move('.assignment-panel','home');
  const cache=frame.querySelector('[data-model-cache-status]')?.parentElement;
  if(cache){const panel=document.createElement('section');panel.className='drawer-panel desktop-models';panel.innerHTML='<h2>Downloaded by InferGrade</h2>';panel.append(cache);pages.get('models').append(panel);}
  move('[aria-labelledby="setup-title"]','models');
  const assignment=pages.get('home').querySelector('[data-assignment-panel]');
  const activitySummary=document.createElement('section');activitySummary.className='drawer-panel';activitySummary.setAttribute('aria-label','Current assignment');pages.get('activity').append(activitySummary);
  const syncAssignment=()=>{activitySummary.replaceChildren();for(const selector of ['[data-assignment-title]','[data-assignment-description]','[data-assignment-phase]','[data-assignment-time]']){const source=assignment?.querySelector(selector);if(source&&!source.closest('[data-assignment-progress-wrap][hidden]')){const line=document.createElement('p');line.textContent=source.textContent;activitySummary.append(line);}}};
  if(assignment)new MutationObserver(syncAssignment).observe(assignment,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['hidden']});syncAssignment();
  const activityLink=document.createElement('button');activityLink.type='button';activityLink.className='button-secondary';activityLink.textContent='View current assignment';activityLink.onclick=()=>showDesktopPage('home');pages.get('activity').append(activityLink);
  move('.log-disclosure','activity');move('.top-bar','settings');move('.observed-runtime-surface','settings');move('[data-support-details]','settings');
  frame.append(sidebar,content);
  const chip=document.querySelector('.connection-chip');if(chip)sidebar.querySelector('[data-desktop-status]').append(chip);
  for(const heading of content.querySelectorAll('h1,h2,h3'))heading.tabIndex=-1;
  for(const button of sidebar.querySelectorAll('[data-desktop-page]'))button.onclick=()=>showDesktopPage(button.dataset.desktopPage);
  sidebar.querySelector('.desktop-brand').onclick=e=>{e.preventDefault();showDesktopPage('home');};
  let lastPaired=null;
  const syncPairing=()=>{const paired=document.documentElement.dataset.paired==='true';if(paired!==lastPaired){const first=lastPaired===null;lastPaired=paired;showDesktopPage(first||paired?'home':'settings',{focus:false});}};
  new MutationObserver(syncPairing).observe(document.documentElement,{attributes:true,attributeFilter:['data-paired']});syncPairing();
}
