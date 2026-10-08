import test from 'node:test';import assert from 'node:assert/strict';
import {activityResultUrl,createResultLoader} from './activityResults.js';
test('result links use paired Hub origin and exact source identity',()=>{
 assert.equal(activityResultUrl('https://api.infergrade.com','qb_exact','compare_context'),'https://infergrade.com/#compare?result=qb_exact');
 assert.equal(activityResultUrl('https://api.infergrade.com','qb_exact','report'),'https://infergrade.com/advanced.html?result=qb_exact');
 for(const args of [['https://token@example.test','qb_exact','report'],['http://untrusted.test','qb_exact','report'],['https://api.infergrade.com','../foreign','report'],['https://api.infergrade.com','qb_exact','invented']])assert.throws(()=>activityResultUrl(...args));
});
test('account change and disconnect discard late private result choices',async()=>{
 let resolve;const applied=[];const errors=[];
 const loader=createResultLoader({fetchResults:()=>new Promise(r=>resolve=r),apply:(...args)=>applied.push(args),onError:(...args)=>errors.push(args)});
 loader.setConnectionKey('old');const old=loader.load('run_old');loader.setConnectionKey('new');resolve({run_id:'run_old',results:[{result_id:'private'}]});await old;assert.equal(applied.length,0);assert.equal(errors.length,0);assert.equal(loader.isCurrent('old'),false);
 const next=loader.load('run_new');loader.setConnectionKey('');resolve({run_id:'run_new',results:[]});await next;assert.equal(applied.length,0);assert.equal(loader.isCurrent('new'),false);
});
test('wrong-run or oversized responses fail visibly and permit retry',async()=>{
 let data={run_id:'foreign',results:[]};const applied=[];const errors=[];
 const loader=createResultLoader({fetchResults:async()=>data,apply:(...args)=>applied.push(args),onError:(...args)=>errors.push(args)});loader.setConnectionKey('machine');await loader.load('run_one');assert.equal(errors.length,1);data={run_id:'run_one',results:new Array(33)};await loader.load('run_one');assert.equal(errors.length,2);data={run_id:'run_one',results:[]};await loader.load('run_one');assert.equal(applied.length,1);
});
