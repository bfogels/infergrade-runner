import test from 'node:test';
import assert from 'node:assert/strict';
import {discoveryRows,selectableLocalModel} from './modelDiscovery.js';
test('read-only discovery requires local path, real finite size, and bounded list',()=>{
 const valid={name:'unknown.gguf',path:'/local/unknown.gguf',size_bytes:4096,read_only:true,identity_status:'unverified'};
 assert.deepEqual(discoveryRows({files:[valid,{...valid,read_only:false},{...valid,size_bytes:NaN},{...valid,path:null}]}),[valid]);
 assert.equal(discoveryRows({files:Array(501).fill(valid)}).length,500);
 assert.deepEqual(discoveryRows(null),[]);
});

test('extensionless discovered HF/Ollama blobs are selectable while arbitrary pasted blobs are not',()=>{
 const path='/cache/hub/blobs/aabb';assert.equal(selectableLocalModel(path,path),true);assert.equal(selectableLocalModel(path,null),false);assert.equal(selectableLocalModel('/another/blob',path),false);assert.equal(selectableLocalModel('/model.gguf'),true);assert.equal(selectableLocalModel(''),false);
});
