async page=>{
 await page.goto('http://127.0.0.1:4189/runner-claude.html');await page.setViewportSize({width:1000,height:700});
 const states={'first-launch':'setup',ready:'ready',running:'running',finished:'done',failed:'failed',offline:'upload','low-disk':'disk','needs-hf-token':'gated','paired-idle':'ready'};
 for(const [name,scenario]of Object.entries(states)){await page.locator('[data-scenario="'+scenario+'"]').click();await page.screenshot({path:'/Users/brianfogelson/Desktop/Code/infergrade/docs/delivery/runner-redesign/mockup-'+name+'.png'});}
 return {mockupStates:Object.keys(states)};
}
