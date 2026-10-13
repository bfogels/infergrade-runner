async page=>{
 await page.setViewportSize({width:1000,height:700});await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
 await page.evaluate(()=>{const original=window.__TAURI_INTERNALS__.invoke;window.__TAURI_INTERNALS__.invoke=(command,args)=>command==='desktop_admission_status'&&window.fixturePauseFailure?Promise.reject(Error('read failed')):original(command,args);window.fixturePauseFailure=true;window.dispatchEvent(new Event('focus'));});
 await page.getByRole('button',{name:'Check pause setting',exact:true}).waitFor();
 if(!await page.getByRole('checkbox',{name:'Pause new benchmarks'}).isDisabled())throw Error('Unknown pause state enabled');
 await page.evaluate(()=>window.fixturePauseFailure=false);await page.getByRole('button',{name:'Check pause setting',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-home-primary]').dataset.action!=='pause-retry');
 if(await page.getByRole('checkbox',{name:'Pause new benchmarks'}).isDisabled())throw Error('Pause retry did not recover');
 return {unknownPauseRequiresAttention:true,unknownPauseCannotWrite:true,retryReadsConfirmedState:true};
}
