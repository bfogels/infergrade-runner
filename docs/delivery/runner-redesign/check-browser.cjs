async page=>{
 const out='/Users/brianfogelson/Desktop/Code/infergrade/docs/delivery/runner-redesign';
 const errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
 await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 const startup=page.getByRole('checkbox',{name:'Open Runner at login'});await startup.waitFor();await startup.focus();await page.keyboard.press('Space');
 await page.waitForFunction(()=>window.fixtureCalls.some(call=>call.command==='set_desktop_startup'&&call.args.enabled===false));
 if(await startup.isChecked())throw Error('Startup did not reflect saved state');
 await page.getByRole('textbox',{name:'Machine name'}).fill('Quiet Mac');await page.keyboard.press('Tab');
 await page.waitForFunction(()=>window.fixtureCalls.some(call=>call.command==='set_desktop_machine_name'&&call.args.label==='Quiet Mac'));
 const pause=page.getByRole('checkbox',{name:'Pause new benchmarks'});await pause.focus();await page.keyboard.press('Space');
 await page.waitForFunction(()=>window.fixtureCalls.some(call=>call.command==='set_desktop_admission_paused'&&call.args.paused===true));
 await page.getByRole('button',{name:'Home',exact:true}).click();await page.getByRole('heading',{name:'Paused',exact:true}).waitFor();
 await page.locator('[data-home-primary]').click();await page.waitForFunction(()=>window.fixtureCalls.some(call=>call.command==='set_desktop_admission_paused'&&call.args.paused===false));
 await page.getByRole('button',{name:'Models',exact:true}).click();const keep=page.getByRole('checkbox',{name:'Keep Qwen3.5-4B-Q4_K_M.gguf'});await keep.focus();await page.keyboard.press('Space');await page.waitForFunction(()=>window.fixtureCalls.some(call=>call.command==='set_desktop_model_keep'&&call.args.keep===true));
 if(!await page.getByRole('button',{name:'Delete',exact:true}).isDisabled())throw Error('Kept model can be deleted');
 await page.getByRole('button',{name:'Check',exact:true}).click();await page.getByRole('button',{name:'Coding',exact:true}).click();if(!await page.getByRole('button',{name:'Coding',exact:true}).getAttribute('aria-pressed'))throw Error('Use-case segment state missing');
 await page.locator('[data-check-panel]').evaluate(node=>node.open=false);
 const results=[];
 for(const theme of ['light','dark']){
  await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:theme[0].toUpperCase()+theme.slice(1),exact:true}).click();
  for(const name of ['Home','Models','Activity','Settings']){
   await page.getByRole('button',{name,exact:true}).click();await page.addScriptTag({path:'/tmp/runner-redesign-a11y/node_modules/axe-core/axe.min.js'});
   const axe=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
   const layout=await page.locator('[data-desktop-content]').evaluate(node=>({scrollHeight:node.scrollHeight,clientHeight:node.clientHeight,overflow:document.documentElement.scrollWidth>innerWidth}));
   results.push({page:name,theme,layout,violations:axe.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))});
   await page.screenshot({path:out+'/checked-'+theme+'-'+name.toLowerCase()+'.png'});
  }
 }
 return {errors,results};
}
