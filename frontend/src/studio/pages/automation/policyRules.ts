import type { AiOperationPolicyPayload } from '../../../types';

/** A rule the owner adds on the permission screen; it applies to every AI client. */
export type NewPolicy = Pick<AiOperationPolicyPayload, 'resource' | 'action' | 'risk' | 'mode' | 'require_mfa'>;

type RuleTarget = Pick<AiOperationPolicyPayload, 'ai_client_id' | 'resource' | 'action' | 'risk'>;

/** What the backend's policies name (ai_policy_service), offered as suggestions; other names are allowed. */
export const POLICY_RESOURCES = [
    'transactions', 'accounts', 'monthly_plan_lines', 'budget_plans', 'auto_transactions', 'registry_entries', 'products',
    'capsules', 'life_events', 'exchange_rates', 'data_transfer', 'data_export', 'client_settings', 'ai_context',
];
export const POLICY_ACTIONS = ['create', 'update', 'delete', 'apply', 'import', 'replace', 'execute', 'read', 'list', 'preview'];

/** The rule direct MCP ledger writes need (transactions / create / medium), at the backend's default mode. */
export function newPolicyDefaults(): NewPolicy {
    return { resource: 'transactions', action: 'create', risk: 'medium', mode: 'require_approval', require_mfa: false };
}

export function policyPayload(row: AiOperationPolicyPayload): AiOperationPolicyPayload {
    // The replacement API needs every policy, but server identity fields are not writable.
    return {
        ai_client_id: row.ai_client_id ?? null, resource: row.resource, action: row.action, risk: row.risk,
        mode: row.mode, threshold_amount: row.threshold_amount ?? null, threshold_count: row.threshold_count ?? null,
        require_mfa: row.require_mfa,
    };
}

/** An added rule as the replacement API takes it, written the way the backend stores it (trimmed, lower case). */
export function newPolicyPayload(rule: NewPolicy): AiOperationPolicyPayload {
    return policyPayload({ ...rule, ai_client_id: null, resource: rule.resource.trim().toLowerCase(), action: rule.action.trim().toLowerCase() });
}

function targetKey(rule: RuleTarget): string {
    return [rule.ai_client_id ?? '', rule.resource.trim().toLowerCase(), rule.action.trim().toLowerCase(), rule.risk].join('\n');
}

/** Why a rule cannot be added: no resource or action, or a rule already covers the same target. */
export function newPolicyProblem(rule: NewPolicy, rules: readonly RuleTarget[]): 'missing' | 'duplicate' | null {
    if (!rule.resource.trim() || !rule.action.trim()) return 'missing';
    const key = targetKey({ ...rule, ai_client_id: null });
    return rules.some((existing) => targetKey(existing) === key) ? 'duplicate' : null;
}
