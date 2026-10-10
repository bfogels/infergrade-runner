async page=>{
 await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'System',exact:true}).click();
 for(const scheme of ['dark','light']){await page.emulateMedia({colorScheme:scheme});await page.waitForFunction(s=>document.documentElement.dataset.theme===s,scheme);}
 await page.locator('[data-support-details] summary').first().focus();await page.keyboard.press('Enter');
 if(!await page.locator('[data-support-details]').evaluate(node=>node.open))throw Error('Keyboard disclosure did not open');
 await page.addScriptTag({path:'/tmp/runner-redesign-a11y/node_modules/axe-core/axe.min.js'});
 const advanced=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
 await page.getByRole('button',{name:'Models',exact:true}).click();await page.locator('[data-check-panel] summary').focus();await page.keyboard.press('Enter');
 const offline=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
 await page.emulateMedia({reducedMotion:'reduce'});await page.getByRole('button',{name:'Home',exact:true}).click();const motion=await page.locator('.mark').evaluate(node=>getComputedStyle(node).animationName);if(motion!=='none')throw Error('Reduced motion ignored');
 return {systemTracksOperatingSystem:true,keyboardDisclosure:true,reducedMotion:true,advancedViolations:advanced.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),offlineViolations:offline.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))};
}
