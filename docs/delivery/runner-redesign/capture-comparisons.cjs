async page=>{
 await page.setViewportSize({width:3080,height:900});await page.goto('http://127.0.0.1:4190/comparison.html');
 for(const state of ['first-launch','ready','running','finished','failed','offline','low-disk','needs-hf-token','paired-idle'])await page.locator('#'+state).screenshot({path:'/Users/brianfogelson/Desktop/Code/infergrade/docs/delivery/runner-redesign/comparison-'+state+'.png'});
 return {comparisonPlates:9};
}
