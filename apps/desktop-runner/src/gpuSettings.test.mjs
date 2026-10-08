import test from 'node:test';
import assert from 'node:assert/strict';
import {gpuSettingsController} from './gpuSettings.js';
const state=revision=>({schema_version:'infergrade.cuda_device_policy.v1',available:true,selection_ready:true,devices:[],policy:revision?{revision}:null});
test('choice waits for native confirmation and coalesces repeated clicks',async()=>{
 let finish,writes=0;const seen=[];
 const controller=gpuSettingsController({read:async()=>state('old'),write:()=>{writes++;return new Promise(resolve=>finish=resolve);},render:s=>seen.push(s)});
 await controller.refresh();const pending=controller.select(['GPU-A']);await controller.select(['GPU-B']);
 assert.equal(writes,1);assert.equal(seen.at(-1).saved.policy.revision,'old');assert.equal(seen.at(-1).pending,true);
 finish(state('new'));await pending;assert.equal(seen.at(-1).saved.policy.revision,'new');assert.equal(seen.at(-1).pending,false);
});
test('failed preference write retains confirmed state and refresh recovers',async()=>{
 const seen=[];let value=state('old');
 const controller=gpuSettingsController({read:async()=>value,write:async()=>{throw Error('private path');},render:s=>seen.push(s)});
 await controller.refresh();await controller.reset();assert.equal(seen.at(-1).saved.policy.revision,'old');assert.ok(seen.at(-1).error);assert.ok(!seen.at(-1).error.includes('private'));
 value=state();await controller.refresh();assert.equal(seen.at(-1).saved.policy,null);assert.equal(seen.at(-1).error,'');
});
test('invalid protocols and cleared generations cannot replace confirmed choice',async()=>{
 const seen=[];let finish;
 const controller=gpuSettingsController({read:()=>new Promise(resolve=>finish=resolve),write:async()=>({schema_version:'future'}),render:s=>seen.push(s)});
 const pending=controller.refresh();controller.clear();finish(state('late'));await pending;assert.equal(seen.at(-1).saved,null);
 await controller.reset();assert.equal(seen.at(-1).saved,null);assert.ok(seen.at(-1).error);
});
