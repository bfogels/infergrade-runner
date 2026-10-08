import test from 'node:test';
import assert from 'node:assert/strict';
import {createStartupController} from './startupSettings.js';
const status=enabled=>({schema_version:'infergrade.startup.v1',available:true,enabled,warning:null});
test('startup never writes on initial read and confirms OS readback',async()=>{
 const rendered=[],writes=[];const controller=createStartupController({read:async()=>status(false),write:async value=>{writes.push(value);return status(value);},render:state=>rendered.push(state)});
 await controller.refresh();assert.deepEqual(writes,[]);await controller.setEnabled(true);assert.deepEqual(writes,[true]);assert.equal(rendered.at(-1).state.enabled,true);
});
test('startup coalesces pending mutations and preserves confirmed value on failure',async()=>{
 let reject;let writes=0;const rendered=[];const controller=createStartupController({read:async()=>status(false),write:()=>{writes++;return new Promise((resolve,r)=>{reject=r;});},render:state=>rendered.push(state)});
 await controller.refresh();const pending=controller.setEnabled(true);await controller.setEnabled(false);assert.equal(writes,1);assert.equal(rendered.at(-1).state.enabled,false);reject(new Error('Could not confirm the OS login setting. Refresh before trying again.'));await pending;assert.equal(rendered.at(-1).state.enabled,false);assert.match(rendered.at(-1).error,/Refresh/);
});
test('startup invalid responses do not become confirmed settings',async()=>{
 let rendered;const controller=createStartupController({read:async()=>({enabled:true}),write:async()=>status(true),render:state=>{rendered=state;}});await controller.refresh();assert.equal(rendered.state,null);assert.ok(rendered.error);
});

test('startup preserves fixed OS instructions for foreign entries',async()=>{
 let rendered;const controller=createStartupController({read:async()=>{throw 'An existing login entry differs from this installation. Remove that entry in your OS login settings before changing this setting.';},write:async()=>status(true),render:state=>{rendered=state;}});await controller.refresh();assert.match(rendered.error,/Remove that entry in your OS login settings/);
});
