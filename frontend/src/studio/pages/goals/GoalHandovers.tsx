import type { GoalBudgetHandoverChoice, GoalBudgetPreview } from '../../../api/goalBudget';
import type { Account } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { DataTable } from '../db/Database';
import { inputClass } from '../db/forms';

/** Suggested handovers into near capsules: each is shown, editable, and only claimed when confirmed. */
export default function GoalHandovers({ preview, chosen, accounts, currency, busy, onChange }: {
    preview: GoalBudgetPreview; chosen: GoalBudgetHandoverChoice[]; accounts: Account[]; currency: string; busy: boolean;
    onChange: (next: GoalBudgetHandoverChoice[]) => void;
}) {
    const suggestions = preview.handover_suggestions;
    // Rows: every suggestion, plus any chosen event the suggestions no longer list.
    const rows = [
        ...suggestions.map((row) => ({ event_id: row.event_id, name: row.name, planned: row.planned, suggested: row.suggested, account_id: row.account_id })),
        ...chosen.filter((item) => !suggestions.some((row) => row.event_id === item.event_id))
            .map((item) => ({ event_id: item.event_id, name: preview.events.find((row) => row.event_id === item.event_id)?.name ?? '', planned: 0, suggested: 0, account_id: item.account_id })),
    ];
    if (!rows.length) return null;
    const update = (eventId: number, patch: Partial<GoalBudgetHandoverChoice> | null, fallback: GoalBudgetHandoverChoice) => {
        const others = chosen.filter((item) => item.event_id !== eventId);
        if (patch === null) return onChange(others);
        const current = chosen.find((item) => item.event_id === eventId) ?? fallback;
        onChange([...others, { ...current, ...patch }]);
    };
    return <>
        <p className="text-sm">遠かったライフイベントが取り置きで積み立てる範囲に入りました。これまで毎月の積立に含めて計画した分を、取り置きへ引き継ぐことを提案します。</p>
        <p className="text-xs text-[var(--studio-text-muted)]">口座のお金は移動しません。口座の残高のうち指定した額を、このライフイベントの取り置きとして確保します（確保額の調整として記録されます）。金額と口座は変更でき、外すと引き継ぎません。</p>
        <DataTable columns={['引き継ぐ', 'ライフイベント', 'これまで計画した額', '確保元の口座', '確保する額', '変化']}>
            {rows.map((row) => {
                const choice = chosen.find((item) => item.event_id === row.event_id);
                const effect = preview.handovers.find((item) => item.event_id === row.event_id);
                const fallback = { event_id: row.event_id, account_id: row.account_id ?? accounts[0]?.id ?? 0, amount: row.suggested };
                return <tr key={`handover-${row.event_id}`}>
                    <td className="px-5 py-3"><input type="checkbox" aria-label={`${row.name}へ引き継ぐ`} disabled={busy || (!choice && !fallback.account_id)} checked={Boolean(choice)} onChange={(event) => update(row.event_id, event.target.checked ? {} : null, fallback)} /></td>
                    <th scope="row" className="px-5 py-3 font-medium">{row.name}{row.suggested > 0 && <span className="mt-1 block text-xs font-normal text-[var(--studio-accent)]">自動の提案 {formatCurrency(row.suggested, currency)}</span>}</th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.planned ? formatCurrency(row.planned, currency) : '—'}</td>
                    <td className="px-5 py-3"><select aria-label={`${row.name}の確保元の口座`} disabled={busy || !choice} value={choice?.account_id ?? fallback.account_id} onChange={(event) => update(row.event_id, { account_id: Number(event.target.value) }, fallback)} className={inputClass}>
                        {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                    </select></td>
                    <td className="w-40 px-5 py-3"><input type="number" min="0" step="any" aria-label={`${row.name}の確保する額`} disabled={busy || !choice} value={choice?.amount ?? fallback.amount} onChange={(event) => update(row.event_id, { amount: Number(event.target.value) || 0 }, fallback)} className={inputClass} /></td>
                    <td className="px-5 py-3 text-xs">{effect ? <>
                        <span className="block tabular-nums">確保済み {formatCurrency(effect.funded_before, currency)} → {formatCurrency(effect.funded_after, currency)}</span>
                        <span className="block tabular-nums">取り置きの月額 {formatCurrency(effect.monthly_before, currency)} → {formatCurrency(effect.monthly_after, currency)}</span>
                        <span className="block tabular-nums text-[var(--studio-text-muted)]">{effect.account_name}の未確保残高 {formatCurrency(effect.available_before, currency)} → {formatCurrency(effect.available_after, currency)}</span>
                        {effect.adds_funding_source && <span className="block text-[var(--studio-text-muted)]">{effect.account_name}を取り置きの資金源に加えます（毎月の積立の配分は変わりません）</span>}
                    </> : <span className="text-[var(--studio-text-muted)]">引き継がない</span>}</td>
                </tr>;
            })}
        </DataTable>
    </>;
}
