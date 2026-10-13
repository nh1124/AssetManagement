import { getCapsules, getCapsuleFundingSources, updateCapsuleFundingSources } from '../../../api';
import type { Capsule, CapsuleFundingSourceInput } from '../../../types';

const percentFormat = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });
export const shareLabel = (share: number | null) => share === null ? '上限なし' : `${percentFormat.format(share / 100)}%`;

export async function loadAllCapsules(): Promise<Capsule[]> {
    const capsules: Capsule[] = [];
    for (let skip = 0; ; skip += 100) {
        const page = await getCapsules(skip, 100);
        capsules.push(...page);
        if (page.length < 100) return capsules;
    }
}

export async function saveAttachment(capsuleId: number, accountId: number, share: number | null | undefined) {
    // PUT replaces the entire list. Read it at save time and preserve every other
    // account's amount, cap and order so editing this account cannot detach them.
    const sources = await getCapsuleFundingSources(capsuleId);
    const payload: CapsuleFundingSourceInput[] = sources
        .filter((source) => share !== undefined || source.account_id !== accountId)
        .map((source) => ({
            account_id: source.account_id, target_amount: source.target_amount,
            max_share_bp: source.account_id === accountId ? share ?? null : source.max_share_bp,
            sort_order: source.sort_order,
        }));
    if (share !== undefined && !sources.some((source) => source.account_id === accountId)) {
        // With every planned amount zero, capsule_service and budget_lines fall
        // back to equal shares; attaching without an amount keeps that routing.
        payload.push({ account_id: accountId, target_amount: 0, max_share_bp: share,
            sort_order: Math.max(-1, ...sources.map((source) => source.sort_order)) + 1 });
    }
    return updateCapsuleFundingSources(capsuleId, payload);
}

