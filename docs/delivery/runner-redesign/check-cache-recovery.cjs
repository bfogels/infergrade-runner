async page=>{
 await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
 await page.getByRole('button',{name:'Models',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-model-cache-status]').textContent.includes('downloaded'));
 await page.evaluate(()=>{
  window.cacheRecoveryInvoke=window.__TAURI_INTERNALS__.invoke;
  window.__TAURI_INTERNALS__.invoke=(command,args)=>command==='desktop_model_cache_status'?Promise.reject(Error('Fixture read failure')):window.cacheRecoveryInvoke(command,args);
  window.dispatchEvent(new Event('focus'));
 });
 const retry=page.getByRole('button',{name:'Retry downloads',exact:true});
 await retry.waitFor();
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByRole('button',{name:'Models',exact:true}).click();
 if(!await retry.isVisible())throw Error('Library render hid download retry');
 if(await page.locator('[data-model-cache-status]').textContent()!=='Could not read downloads. Try again.')throw Error('Download error was replaced');
 await page.evaluate(()=>{window.__TAURI_INTERNALS__.invoke=window.cacheRecoveryInvoke;});
 await retry.click();
 await page.waitForFunction(()=>document.querySelector('[data-model-cache-status]').textContent.includes('downloaded'));
 if(await retry.isVisible())throw Error('Successful read did not clear retry');
 return {errorSurvivesLibraryRender:true,retryHandlerPreserved:true,successfulReadClearsError:true};
}
