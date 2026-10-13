async page=>{
 await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
 return await page.evaluate(async()=>{
  const {patchView}=await import('/src/desktopState.js');
  const target=document.createElement('section');document.body.append(target);
  const row=id=>`<article data-activity-run-id="${id}"><button>${id}</button><details><summary>Logs</summary><p>Log</p></details></article>`;
  patchView(target,row('a')+row('b'));const original=target.querySelector('[data-activity-run-id="b"] button');let invoked='';original.onclick=()=>invoked='b';original.focus();target.querySelector('[data-activity-run-id="b"] details').open=true;
  patchView(target,row('b')+row('c'));
  if(document.activeElement!==original)throw Error('Polling lost focused run identity');original.click();if(invoked!=='b')throw Error('Polling lost handler');
  if(!target.querySelector('details').open)throw Error('Polling collapsed disclosure');
  patchView(target,'<input aria-label="draft" value="saved">');const input=target.querySelector('input');input.value='draft';input.focus();patchView(target,'<input aria-label="draft" value="server">');if(input.value!=='draft'||document.activeElement!==input)throw Error('Polling overwrote draft');
  patchView(target,'<input type="checkbox" checked>');patchView(target,'<input type="checkbox">');if(target.querySelector('input').checked)throw Error('Saved checkbox state not rendered');target.remove();
  return {focusedRunIdentity:true,eventHandlerPreserved:true,openDisclosurePreserved:true,draftPreserved:true,confirmedCheckbox:true};
 });
}
