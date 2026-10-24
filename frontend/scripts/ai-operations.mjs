// What 自動化 › AI操作 shows beside a permission (WP36, WP37): the same order the backend decides in
// (ai_policy_service.mcp_refusal), so the screen never promises what the gate refuses.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/studio/pages/automation/operationRules.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
vm.runInNewContext(outputText, {
    exports,
    require: (name) => { throw new Error(`Unexpected runtime dependency: ${name}`); },
});
const { operationEffect, effectTag } = exports;

const read = { kind: 'read', approval: false, by_write_mode: true };
const write = { kind: 'write', approval: false, by_write_mode: true };
const approvable = { kind: 'write', approval: true, by_write_mode: true };
const requestOperation = { kind: 'write', approval: false, by_write_mode: false };

// Reads ignore the write mode.
for (const writeMode of ['direct_write', 'change_request']) {
    assert.equal(operationEffect(read, 'allow', writeMode, true), 'read');
    assert.equal(operationEffect(read, 'deny', writeMode, true), 'no_read');
}
// Direct writes need both "allow" and the direct write mode.
assert.equal(operationEffect(write, 'allow', 'direct_write', true), 'direct');
assert.equal(operationEffect(write, 'allow', 'change_request', true), 'not_in_mode');
assert.equal(operationEffect(write, 'deny', 'direct_write', true), 'denied');
// An operation a change request can carry goes through one when it is not allowed directly.
assert.equal(operationEffect(approvable, 'allow', 'direct_write', true), 'direct');
assert.equal(operationEffect(approvable, 'approval', 'direct_write', true), 'through_approval');
assert.equal(operationEffect(approvable, 'allow', 'change_request', true), 'through_approval');
assert.equal(operationEffect(approvable, 'approval', 'change_request', true), 'through_approval');
assert.equal(operationEffect(approvable, 'deny', 'change_request', true), 'denied');
// ...unless the AI may not create change requests at all.
assert.equal(operationEffect(approvable, 'approval', 'direct_write', false), 'no_requests');
assert.equal(operationEffect(approvable, 'allow', 'direct_write', false), 'direct');
// The change-request operations themselves work in either write mode.
assert.equal(operationEffect(requestOperation, 'allow', 'change_request', true), 'available');
assert.equal(operationEffect(requestOperation, 'deny', 'direct_write', true), 'denied');

// A tag appears only where the chosen permission is not what happens.
assert.equal(effectTag(write, 'allow', 'direct_write', true), null);
assert.equal(effectTag(write, 'deny', 'change_request', true), null);
assert.equal(effectTag(read, 'allow', 'change_request', true), null);
assert.equal(effectTag(write, 'allow', 'change_request', true), 'unavailable');
assert.equal(effectTag(approvable, 'allow', 'change_request', true), 'via_approval');
assert.equal(effectTag(approvable, 'approval', 'change_request', true), null);
assert.equal(effectTag(approvable, 'approval', 'direct_write', false), 'unavailable');
assert.equal(effectTag(requestOperation, 'allow', 'change_request', true), null);

console.log('AI operations: the tags beside a permission follow the backend gate in both write modes');
