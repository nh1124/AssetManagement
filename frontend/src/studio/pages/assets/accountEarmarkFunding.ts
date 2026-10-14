import { getCapsules, getCapsuleFundingSources, updateCapsuleFundingSources } from '../../../api';
import type { Capsule, CapsuleFundingSourceInput } from '../../../types';

export async function loadAllCapsules(): Promise<Capsule[]> {
    const capsules: Capsule[] = [];
    for (let skip = 0; ; skip += 100) {
        const page = await getCapsules(skip, 100);
        capsules.push(...page);
        if (page.length < 100) return capsules;
    }
}

export async function saveAttachment(capsuleId: number, accountId: number, attached: boolean): Promise<boolean> {
    // PUT replaces the entire list. Read it at save time and preserve every other
    // account's amount, cap and order so editing this account cannot detach them.
    const sources = await getCapsuleFundingSources(capsuleId);
    if (sources.some((source) => source.account_id === accountId) === attached) return false;
    const payload: CapsuleFundingSourceInput[] = sources
        .filter((source) => attached || source.account_id !== accountId)
        .map((source) => ({
            account_id: source.account_id, target_amount: source.target_amount,
            max_share_bp: source.max_share_bp,
            sort_order: source.sort_order,
        }));
    if (attached) {
        // With every planned amount zero, capsule_service and budget_lines fall
        // back to equal shares; attaching without an amount keeps that routing.
        // Per-account drawdowns are bounded by actual claims. Declared caps now
        // only feed the 100% declaration check and one health warning, both of
        // which skip null; keep existing caps without a column drop or migration.
        payload.push({ account_id: accountId, target_amount: 0, max_share_bp: null,
            sort_order: Math.max(-1, ...sources.map((source) => source.sort_order)) + 1 });
    }
    await updateCapsuleFundingSources(capsuleId, payload);
    return true;
}

