import test from 'node:test';
import assert from 'node:assert/strict';
import {storageController,storageState} from './storageControls.js';
const gib=1024**3;
const state=(limit=50,bytes=30*gib)=>({schema_version:'infergrade.cache_budget.v1',limit_gb:limit,limit_bytes:limit===null?null:limit*gib,managed_bytes:bytes,kept_bytes:10*gib,reserved_bytes:0,producer_active:false,disk_free_bytes:100*gib,disk_total_bytes:256*gib});
test('lower limit requires confirmation; cancel retains exact confirmed state and performs no write',async()=>{
 const seen=[];let writes=0,asked;
 const c=storageController({read:async()=>state(),write:async()=>{writes++;},confirmTrim:async limit=>{asked=limit;return false;},render:s=>seen.push(s)});
 await c.refresh();const original=seen.at(-1).saved;await c.setLimit(25);
 assert.equal(asked,25);assert.equal(writes,0);assert.equal(seen.at(-1).saved,original);assert.equal(seen.at(-1).pending,false);assert.equal(seen.at(-1).error,'');
});
test('confirmed trimming coalesces clicks and changes only after native confirmation',async()=>{
 const seen=[];let finish,writes=0,args;
 const c=storageController({read:async()=>state(),write:(...a)=>{writes++;args=a;return new Promise(r=>finish=r);},confirmTrim:async()=>true,render:s=>seen.push(s)});
 await c.refresh();const pending=c.setLimit(25);await Promise.resolve();await c.setLimit(100);
 assert.equal(writes,1);assert.deepEqual(args,[25,true]);assert.equal(seen.at(-1).saved.limit_gb,50);finish(state(25,20*gib));await pending;assert.equal(seen.at(-1).saved.limit_gb,25);
});
test('failed or lost save preserves last confirmation and fences new writes until refresh',async()=>{
 const seen=[];let writes=0;
 const c=storageController({read:async()=>state(),write:async()=>{writes++;throw Error('/private/file');},confirmTrim:async()=>true,render:s=>seen.push(s)});
 await c.refresh();await c.setLimit(25);assert.equal(seen.at(-1).saved.limit_gb,50);assert.ok(seen.at(-1).error);assert.ok(!seen.at(-1).error.includes('/private'));
 await c.setLimit(100);assert.equal(writes,1);await c.refresh();assert.equal(seen.at(-1).error,'');
});
test('unlimited and sufficient capacity updates do not ask to delete',async()=>{
 const seen=[];let args,confirmed=0;
 const c=storageController({read:async()=>state(),write:async(...a)=>{args=a;return state(a[0]);},confirmTrim:()=>{throw Error('unexpected');},render:s=>seen.push(s),confirmed:()=>confirmed++});
 await c.refresh();await c.setLimit(null);assert.deepEqual(args,[null,false]);assert.equal(seen.at(-1).saved.limit_gb,null);await c.setLimit(100);assert.deepEqual(args,[100,false]);assert.equal(confirmed,2);
});
test('unknown, invalid, stale response and mismatched saved limit cannot become confirmed',async()=>{
 const seen=[];let finish;
 const c=storageController({read:()=>new Promise(r=>finish=r),write:async()=>state(100),confirmTrim:async()=>true,render:s=>seen.push(s)});
 await c.setLimit(25);assert.equal(seen.length,0);const pending=c.refresh();c.clear();finish(state());await pending;assert.equal(seen.at(-1).saved,null);
 for(const bad of [{}, {...state(),extra:'path'}, {...state(),managed_bytes:-1}, {...state(),limit_bytes:25}, {...state(),reserved_bytes:1}, {...state(),kept_bytes:31*gib}, {...state(),disk_free_bytes:300*gib}])assert.throws(()=>storageState(bad));
 const mismatch=storageController({read:async()=>state(),write:async()=>state(100),confirmTrim:async()=>true,render:s=>seen.push(s)});await mismatch.refresh();await mismatch.setLimit(25);assert.equal(seen.at(-1).saved.limit_gb,50);assert.ok(seen.at(-1).error);
});
test('late deletion confirmation cannot write after controller generation clears',async()=>{
 const seen=[];let approve,writes=0;
 const c=storageController({read:async()=>state(),write:async()=>{writes++;return state(25);},confirmTrim:()=>new Promise(r=>approve=r),render:s=>seen.push(s)});
 await c.refresh();const pending=c.setLimit(25);c.clear();approve(true);await pending;assert.equal(writes,0);assert.equal(seen.at(-1).saved,null);
});
