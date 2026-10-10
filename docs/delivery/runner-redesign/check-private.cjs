async page=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
 await page.getByRole('button',{name:'Models',exact:true}).click();await page.locator('[data-check-panel] summary').click();
 await page.locator('[data-private-path]').fill('/fixture/local.gguf');await page.locator('[data-private-start]').click();
 await page.getByRole('heading',{name:'Running',exact:true}).waitFor();await page.locator('[data-home-primary]').click();
 if(!await page.locator('[data-slot="private-running"] h2').evaluate(node=>document.activeElement===node))throw Error('Private current-run action has wrong focus');
 await page.evaluate(()=>window.fixturePrivateStatus={status:'failed',pid:null,phase:'The local model failed to load.'});
 await page.getByRole('heading',{name:'Needs attention',exact:true}).waitFor();await page.locator('[data-home-primary]').click();
 if(!await page.locator('[data-slot="private-running"] h2').evaluate(node=>document.activeElement===node))throw Error('Private failure action has wrong focus');
 await page.evaluate(()=>window.fixturePrivateStatus={status:'completed',pid:null,phase:'Local report saved.'});
 await page.locator('[data-private-status]').click();await page.getByRole('heading',{name:'Needs attention',exact:true}).waitFor();
 if(await page.locator('[data-home-primary]').getAttribute('data-action')==='run')throw Error('Private failure latched after completion');
 return {errors,privateRunningFocus:true,privateFailureHero:true,privateFailureFocus:true,terminalRecovery:true};
}
