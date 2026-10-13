async page=>{
 await page.setViewportSize({width:1000,height:700});await page.goto('http://127.0.0.1:1420/?scenario=paired-idle');
 await page.getByRole('button',{name:'Settings',exact:true}).click();await page.locator('[data-support-details] summary').first().click();
 await page.getByRole('button',{name:'Check local endpoint',exact:true}).click();
 if(!await page.locator('[data-check-panel]').evaluate(node=>node.open))throw Error('Endpoint disclosure stayed closed');
 if(!await page.locator('[data-observed-runtime-panel] h2').evaluate(node=>document.activeElement===node))throw Error('Endpoint shortcut lost focus');
 if(!await page.locator('[data-observed-runtime-panel]').isVisible())throw Error('Endpoint panel not visible');
 await page.addScriptTag({path:'/tmp/runner-redesign-a11y/node_modules/axe-core/axe.min.js'});
 const audit=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
 if(audit.violations.length)throw Error(JSON.stringify(audit.violations.map(v=>v.id)));
 return {advancedEndpointShortcut:true,offlineDisclosureOpen:true,endpointHeadingFocused:true,violations:[]};
}
