import test from 'node:test';import assert from 'node:assert/strict';
import {backgroundSummary} from './backgroundSettings.js';
test('background copy depends on actual tray and saved preference, with failures visible',()=>{
 assert.match(backgroundSummary({keep_running:true,tray_available:false}),/unavailable/);
 assert.match(backgroundSummary({keep_running:true,tray_available:true}),/keeps Runner working/);
 assert.match(backgroundSummary({keep_running:false,tray_available:true}),/quits when Runner is idle/);
 assert.equal(backgroundSummary({keep_running:true,tray_available:true,warning:'Save failed'}),'Save failed');
});
