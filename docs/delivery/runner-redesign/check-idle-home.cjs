async page=>{
 await page.setViewportSize({width:1000,height:700});
 const outcomes=[];
 for(const failure of [false,true]) {
  await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
  await page.locator('[data-home-primary]').click();
  await page.getByRole('button',{name:'Home',exact:true}).click();
  if(await page.locator('[data-assignment-panel]').isVisible())throw Error('Empty setup appears as a run');
  await page.evaluate(failure=>{const original=window.__TAURI_INTERNALS__.invoke;window.__TAURI_INTERNALS__.invoke=(command,args)=>command==='run_desktop_native_first_run'?failure?Promise.reject(Error('fixture local check failed')):Promise.resolve({artifact:{path:'/fixture/result.json'},bundle_artifact:{path:'/fixture/bundle.json'},result:{metrics:{}}}):original(command,args);},failure);
  await page.getByRole('button',{name:'Check a model offline',exact:true}).click();
  await page.locator('[name="firstRunModelPath"]').fill('/fixture/local.gguf');
  await page.getByRole('button',{name:'Run local check',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-first-run-status]').textContent.includes('Completed native')||document.querySelector('[data-first-run-status]').textContent.includes('Native first-run failed'));
  await page.getByRole('button',{name:'Settings',exact:true}).click();await page.locator('[data-support-details]').evaluate(n=>n.open=true);
  await page.getByRole('button',{name:'Make ready',exact:true}).click();
  await page.getByRole('button',{name:'Home',exact:true}).click();
  if(!await page.locator('[data-assignment-panel]').isVisible())throw Error('Local outcome hidden after setup check');
  if(!failure)for(const name of ['Copy artifact path','Check again','Choose another model'])if(!await page.getByRole('button',{name,exact:true}).isVisible())throw Error('Recovery hidden: '+name);
  outcomes.push({failure,localOutcomePreserved:true,artifactRecovery:failure?"not applicable":true});
 }
 return {emptySetupHidden:true,outcomes};
}
