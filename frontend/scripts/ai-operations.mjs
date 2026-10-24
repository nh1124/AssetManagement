// What 自動化 › AI操作 shows as 今の扱い, and its search (WP36): the same order the backend
// decides in (ai_policy_service.mcp_refusal), so the screen never promises what the gate refuses.
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
const { operationEffect, operationMatches } = exports;

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

const operation = { kind: 'write', key: 'transactions.create', ja: '取引を記録する', en: 'Record a transaction', tools: ['transactions_create', 'transaction_batches_create'] };
assert.equal(operationMatches(operation, '', 'all'), true);
assert.equal(operationMatches(operation, '', 'read'), false);
assert.equal(operationMatches(operation, '取引', 'write'), true);
assert.equal(operationMatches(operation, 'RECORD', 'all'), true);
assert.equal(operationMatches(operation, 'batches_create', 'all'), true);
assert.equal(operationMatches(operation, ' transactions  記録 ', 'all'), true);
assert.equal(operationMatches(operation, 'transactions 削除', 'all'), false);

console.log('AI operations: 今の扱い follows the backend gate in both write modes, and the search covers names, keys and tools');
