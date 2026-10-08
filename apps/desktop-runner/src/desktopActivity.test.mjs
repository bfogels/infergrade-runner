import test from 'node:test';import assert from 'node:assert/strict';
import {activityGroups,createActivityLoader,activityRunUrl} from './desktopActivity.js';
test('queued/running/terminal history stays distinct without inventing completed progress',()=>{
 const groups=activityGroups({runs:[{run_id:'running',status:'running',progress_percent:0},{run_id:'queued',status:'awaiting_execution'},{run_id:'failed',status:'failed'},{run_id:'complete',status:'completed',progress_percent:null},{run_id:'paused',status:'paused'},{run_id:'bad',status:'invented'}]});
 assert.equal(groups.active[0].progress_percent,0);assert.equal(groups.queued.length,1);assert.equal(groups.attention.length,1);assert.equal(groups.finished.length,2);assert.equal(groups.finished[1].progress_percent,null);
});
test('disconnect clears history and fences a delayed private response',async()=>{
 let resolve;const renders=[];let calls=0;const loader=createActivityLoader({fetchActivity:()=>{calls++;return new Promise(r=>resolve=r);},render:(p,key)=>renders.push({p,key}),onError:()=>assert.fail('unexpected error')});
 loader.setConnectionKey('first');const pending=loader.refresh();await loader.refresh();assert.equal(calls,1);loader.setConnectionKey('');resolve({runs:[{run_id:'private'}]});await pending;assert.deepEqual(renders.map(r=>r.p),[null,null]);await loader.refresh();assert.equal(calls,1);
});
test('new connection can load before an old request finishes, without stale overwrite',async()=>{
 const pending=[];const renders=[];const loader=createActivityLoader({fetchActivity:()=>new Promise(r=>pending.push(r)),render:(p,key)=>renders.push({p,key}),onError:()=>{}});loader.setConnectionKey('old');const old=loader.refresh();loader.setConnectionKey('new');const fresh=loader.refresh();pending[1]({runner_id:'new'});await fresh;pending[0]({runner_id:'old'});await old;assert.deepEqual(renders.at(-1),{p:{runner_id:'new'},key:'new'});
});

test('history links use the saved paired API destination and never form settings',()=>{
 assert.equal(activityRunUrl('https://api.infergrade.com','run_real'),'https://infergrade.com/runs?run=run_real');
 assert.equal(activityRunUrl('http://127.0.0.1:8055','run_real'),'http://127.0.0.1:8055/runs?run=run_real');
 assert.throws(()=>activityRunUrl('http://untrusted.example','run_real'));assert.throws(()=>activityRunUrl('https://token@example.test','run_real'));assert.throws(()=>activityRunUrl('https://api.infergrade.com','../../private'));
});
