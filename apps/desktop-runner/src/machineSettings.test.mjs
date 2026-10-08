import test from 'node:test';
import assert from 'node:assert/strict';
import {machineNameController} from './machineSettings.js';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('a late name response cannot overwrite another paired machine',async()=>{
 const pending=[];const states=[];
 const controller=machineNameController({read:()=>new Promise(resolve=>pending.push(resolve)),save:()=>assert.fail('unexpected save'),apply:s=>states.push(s)});
 controller.setConnectionKey('runner_old|https://api.infergrade.com');
 controller.setConnectionKey('runner_new|https://api.infergrade.com');
 pending[1]({runner_id:'runner_new',label:'Study Mac'});await tick();
 pending[0]({runner_id:'runner_old',label:'Old private name'});await tick();
 assert.equal(states.at(-1).name,'Study Mac');
 controller.setConnectionKey('');assert.equal(states.at(-1).name,'');
});
test('failed save keeps the confirmed name and allows retry',async()=>{
 const states=[];let fail=true;const saved=[];
 const controller=machineNameController({read:async()=>({runner_id:'runner_one',label:'Desk Mac'}),save:async label=>{saved.push(label);if(fail)throw new Error('Check connection');return{runner_id:'runner_one',label};},apply:s=>states.push(s)});
 controller.setConnectionKey('runner_one|api');await tick();
 await controller.save('  Study Mac  ');assert.equal(states.at(-1).name,'Desk Mac');assert.equal(states.at(-1).error,'Check connection');assert.equal(states.at(-1).busy,false);
 fail=false;await controller.save('Study Mac');assert.equal(states.at(-1).name,'Study Mac');assert.deepEqual(saved,['Study Mac','Study Mac']);
});
test('disconnect during a save clears private name and rejects late response',async()=>{
 let resolve;const states=[];const controller=machineNameController({read:async()=>({runner_id:'runner_one',label:'Desk Mac'}),save:()=>new Promise(r=>resolve=r),apply:s=>states.push(s)});
 controller.setConnectionKey('runner_one|api');await tick();const request=controller.save('Study Mac');controller.setConnectionKey('');resolve({runner_id:'runner_one',label:'Study Mac'});await request;assert.equal(states.at(-1).name,'');assert.equal(states.at(-1).busy,false);
});
test('invalid labels and wrong-machine responses never become confirmed names',async()=>{
 const states=[];let writes=0;const controller=machineNameController({read:async()=>({runner_id:'runner_other',label:'Private name'}),save:()=>{writes++;},apply:s=>states.push(s)});
 controller.setConnectionKey('runner_one|api');await tick();assert.equal(states.at(-1).name,'');assert.match(states.at(-1).error,/different machine/);
 for(const label of ['', 'x'.repeat(121), 'Bad\nName','Bad\u0085Name'])await controller.save(label);
 assert.equal(writes,0);assert.match(states.at(-1).error,/1–120/);
});
