// The rules 自動化 › AI adds: an owner with no saved rules can add the one direct
// MCP ledger writes need, and the replacement payload keeps every other rule.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/studio/pages/automation/policyRules.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
vm.runInNewContext(outputText, {
    exports,
    require: (name) => { throw new Error(`Unexpected runtime dependency: ${name}`); },
});
const { newPolicyDefaults, newPolicyPayload, newPolicyProblem, policyPayload } = exports;

// The form starts at the ledger rule, at the backend's default mode: adding it unchanged opens nothing.
const draft = newPolicyDefaults();
assert.deepEqual({ ...draft }, { resource: 'transactions', action: 'create', risk: 'medium', mode: 'require_approval', require_mfa: false });
assert.equal(newPolicyProblem(draft, []), null);

assert.deepEqual({ ...newPolicyPayload({ ...draft, mode: 'allow_execute' }) }, {
    ai_client_id: null, resource: 'transactions', action: 'create', risk: 'medium',
    mode: 'allow_execute', threshold_amount: null, threshold_count: null, require_mfa: false,
});
// Written the way the backend stores it.
assert.equal(newPolicyPayload({ ...draft, resource: ' Transactions ', action: 'CREATE' }).resource, 'transactions');
assert.equal(newPolicyPayload({ ...draft, resource: ' Transactions ', action: 'CREATE' }).action, 'create');

assert.equal(newPolicyProblem({ ...draft, resource: '  ' }, []), 'missing');
assert.equal(newPolicyProblem({ ...draft, action: '' }, []), 'missing');

const saved = {
    id: 4, client_id: 2, ai_client_id: null, resource: 'transactions', action: 'create', risk: 'medium',
    mode: 'require_approval', threshold_amount: 5000, threshold_count: null, require_mfa: true,
    created_at: '2026-10-24T00:00:00', updated_at: '2026-10-24T00:00:00',
};
assert.equal(newPolicyProblem(draft, [saved]), 'duplicate');
assert.equal(newPolicyProblem({ ...draft, resource: 'TRANSACTIONS ' }, [saved]), 'duplicate');
assert.equal(newPolicyProblem({ ...draft, risk: 'high' }, [saved]), null);
assert.equal(newPolicyProblem({ ...draft, action: 'update' }, [saved]), null);
// A rule for one AI client does not cover every client.
assert.equal(newPolicyProblem(draft, [{ ...saved, ai_client_id: 9 }]), null);
// Two rules added in one sitting collide too.
assert.equal(newPolicyProblem(draft, [newPolicyPayload(draft)]), 'duplicate');

// A saved rule goes back without its server fields, thresholds kept.
assert.deepEqual({ ...policyPayload(saved) }, {
    ai_client_id: null, resource: 'transactions', action: 'create', risk: 'medium',
    mode: 'require_approval', threshold_amount: 5000, threshold_count: null, require_mfa: true,
});

console.log('AI permission rules: the ledger rule can be added with no saved rules, duplicates are refused, saved rules round-trip');
