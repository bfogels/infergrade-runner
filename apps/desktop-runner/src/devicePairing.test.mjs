import test from 'node:test';
import assert from 'node:assert/strict';
import {devicePairingController} from './devicePairing.js';
const issued={session_id:'1',user_code:'ABCD-2345',verification_uri:'https://infergrade.com/connect?code=ABCD-2345',interval:1,expires_in:10};
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
function setup(invoke){const events=[];const controller=devicePairingController({invoke,openExternal:async url=>events.push(['open',url]),onIssued:value=>events.push(['issued',value]),onStatus:message=>events.push(['status',message]),onPaired:value=>events.push(['paired',value]),onActive:value=>events.push(['active',value]),onCompleting:value=>events.push(['completing',value]),onStopped:async()=>events.push(['stopped'])});return {events,controller};}
test('approved flow opens only short-code URL and passes sanitized pairing to normal startup',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date'],now:0});const calls=[];
 const {events,controller}=setup(async(name,args)=>{calls.push([name,args]);if(name==='begin_runner_device_pairing')return issued;if(name==='poll_runner_device_pairing')return {status:'paired',pairing:{runner_id:'actual-native-response'}};});
 const running=controller.start('https://api.infergrade.com','Mac');await flush();t.mock.timers.tick(1000);await running;
 assert.equal(events.find(event=>event[0]==='open')[1],issued.verification_uri);
 assert.deepEqual(events.find(event=>event[0]==='paired')[1],{runner_id:'actual-native-response'});
 assert.deepEqual(calls.find(call=>call[0]==='poll_runner_device_pairing')[1],{sessionId:'1'});
 assert.equal(controller.isActive(),false);
});
test('cancel fences a late issue response and never opens a browser or polls',async()=>{
 let resolveIssue;const calls=[];const {events,controller}=setup(async name=>{calls.push(name);if(name==='begin_runner_device_pairing')return new Promise(resolve=>{resolveIssue=resolve;});});
 const running=controller.start('https://api.infergrade.com','Mac');await flush();await controller.cancel();resolveIssue(issued);await running;
 assert.ok(!events.some(event=>event[0]==='open'||event[0]==='paired'));
 assert.ok(!calls.includes('poll_runner_device_pairing'));assert.equal(controller.isActive(),false);
});
test('cancel fences a late approval response and startup never uses it',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date'],now:0});let resolvePoll;
 const {events,controller}=setup(async name=>{if(name==='begin_runner_device_pairing')return issued;if(name==='poll_runner_device_pairing')return new Promise(resolve=>{resolvePoll=resolve;});});
 const running=controller.start('https://api.infergrade.com','Mac');await flush();t.mock.timers.tick(1000);await flush();await controller.cancel();resolvePoll({status:'paired',pairing:{runner_id:'late'}});await running;
 assert.ok(!events.some(event=>event[0]==='paired'));assert.equal(controller.isActive(),false);
});
test('network retries remain bounded by expiry and denial is terminal',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date'],now:0});let polls=0;
 const {events,controller}=setup(async name=>{if(name==='begin_runner_device_pairing')return {...issued,expires_in:3};if(name==='poll_runner_device_pairing'){polls++;throw new Error('network unavailable');}});
 const running=controller.start('https://api.infergrade.com','Mac');await flush();for(let i=0;i<3;i++){t.mock.timers.tick(1000);await flush();}await running;
 assert.equal(polls,2);assert.ok(events.some(event=>event[0]==='status'&&event[1].includes('expired')));assert.equal(controller.isActive(),false);
 const denied=setup(async name=>name==='begin_runner_device_pairing'?issued:{status:'denied'});const second=denied.controller.start('https://api.infergrade.com','Mac');await flush();t.mock.timers.tick(1000);await second;assert.ok(denied.events.some(event=>event[0]==='status'&&event[1].includes('declined')));assert.ok(!denied.events.some(event=>event[0]==='paired'));
});

test('approval is terminal before asynchronous startup and Stop waiting cannot interrupt it',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date'],now:0});let finishStartup;const events=[];
 const controller=devicePairingController({invoke:async name=>name==='begin_runner_device_pairing'?issued:{status:'paired',pairing:{}},openExternal:async()=>{},onIssued:()=>{},onStatus:()=>{},onActive:()=>{},onCompleting:value=>events.push(['completing',value]),onStopped:()=>events.push(['stopped']),onPaired:async()=>{events.push(['startup']);await new Promise(resolve=>{finishStartup=resolve;});}});
 const running=controller.start('https://api.infergrade.com','Mac');await flush();t.mock.timers.tick(1000);await flush();assert.deepEqual(events.slice(0,2),[['completing',true],['startup']]);await controller.cancel();assert.ok(!events.some(event=>event[0]==='stopped'));finishStartup();await running;assert.equal(controller.isActive(),false);
});
