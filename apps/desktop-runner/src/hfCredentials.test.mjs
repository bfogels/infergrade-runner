import test from 'node:test';
import assert from 'node:assert/strict';
import {hfCredentialSummary} from './hfCredentials.js';
test('credential summary distinguishes environment precedence from saved state',()=>{
  assert.match(hfCredentialSummary({saved:true,environment_override:true}),/does not unset/);
  assert.match(hfCredentialSummary({saved:true,environment_override:false}),/OS credential store/);
  assert.equal(hfCredentialSummary({saved:false}),'No token saved by Runner.');
  assert.doesNotMatch(hfCredentialSummary({saved:true,token:'private-value'}),/private-value/);
});
