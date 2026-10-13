import { clientToday, useTimezone } from '../../datetime';
import { useCallback, useState } from 'react';
import { applyReviewAction, createMonthlyAction, getMonthlyActions, processDueMonthlyActions, skipReviewAction } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { MonthlyAction, ReviewActionCreate } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';
import MonthPicker from '../ledger/MonthPicker';
import ActionEditor from './ActionEditor';

const STATES: Record<MonthlyAction['status'], string> = { pending: '未実行', applied: '実行済み', skipped: '見送り', failed: '失敗' };
const KINDS: Record<string, string> = { set_budget: '支出予算を設定', add_recurring: '定常収支を追加', pause_recurring: '定常収支を停止', boost_allocation: 'ゴールへの確保額を変更', change_capsule_contribution: '取り置きの月額積立を変更' };

function RelatedBudget({ action, currency }: { action: MonthlyAction; currency: string }) {
    const payload = action.payload;
    const code = typeof payload.currency === 'string' ? payload.currency : currency;
    const accountId = payload.account_id ?? payload.to_account_id;
    const label = action.kind === 'set_budget' ? `支出予算・勘定科目 #${String(accountId ?? '—')}`
        : action.kind === 'boost_allocation' ? `ゴール #${String(payload.life_event_id ?? '—')}・口座 #${String(accountId ?? '—')}`
            : action.kind === 'change_capsule_contribution' ? `取り置き #${String(action.target_id ?? '—')}`
                : action.kind === 'pause_recurring' ? `定常収支 #${String(payload.recurring_id ?? action.target_id ?? '—')}`
                    : action.kind === 'add_recurring' ? `${String(payload.name ?? '定常収支')}・${String(payload.from_account_id ?? '—')} → ${String(payload.to_account_id ?? '—')}` : '—';
    const amount = payload.amount ?? payload.monthly_contribution ?? action.amount;
    return <div className="space-y-1 text-xs"><p>{label}</p>
        {typeof amount === 'number' && <p className="tabular-nums">{formatCurrency(amount, code)}（{code}）</p>}
        {action.kind === 'boost_allocation' && typeof (payload.delta_percent ?? payload.percent) === 'number' && <p>{String(payload.delta_percent ?? payload.percent)}%</p>}
        {typeof action.result.plan_line_id === 'number' && <p>予算行 #{action.result.plan_line_id}</p>}
    </div>;
}

function MonthlyActions({ sourcePeriod, currency, clientName }: { sourcePeriod: string; currency: string; clientName?: string }) {
    const load = useCallback(() => getMonthlyActions(sourcePeriod), [sourcePeriod]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [adding, setAdding] = useState(false);
    const [processed, setProcessed] = useState<MonthlyAction[] | null>(null);
    const disabled = mutation.busy || resource.loading || Boolean(resource.error) || !clientName;
    const save = (payload: ReviewActionCreate) => {
        if (disabled) return;
        void mutation.run(() => createMonthlyAction(payload), '行動を未実行として追加しました。', () => { setAdding(false); resource.reload(); });
    };
    const decide = (action: MonthlyAction, apply: boolean) => {
        if (disabled || adding || action.status !== 'pending') return;
        const verb = apply ? '実行' : '見送り';
        if (!window.confirm(`「${clientName}」の「${action.description || KINDS[action.kind] || action.kind}」を${verb}にしますか？${apply ? '\n関連する予算・定義・確保額に変更を反映します。予定月が将来でも、今すぐ実行します。' : ''}`)) return;
        let updated: MonthlyAction | null = null;
        void mutation.run(async () => { updated = await (apply ? applyReviewAction(action.id) : skipReviewAction(action.id)); }, `行動を${verb}にしました。`, () => {
            const result = updated;
            resource.setData((previous) => result ? previous?.map((row) => row.id === result.id ? result : row) ?? null : previous);
            resource.reload();
        });
    };
    const processDue = () => {
        if (disabled || adding || !window.confirm(`「${clientName}」の期限が到来した行動を実行しますか？\n表示中の記録月にかかわらず、全期間の未実行・失敗した行動を対象に、関連する予算・定義・確保額へ反映します。`)) return;
        let rows: MonthlyAction[] = [];
        void mutation.run(async () => { rows = (await processDueMonthlyActions()).processed; }, '期限が到来した行動の処理が完了しました。', () => { setProcessed(rows); resource.reload(); });
    };
    return <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-lg font-semibold">行動</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">{sourcePeriod}に記録した行動 ／ 対象：{clientName || 'クライアントを確認中…'}</p></div>
            <div className="flex flex-wrap gap-2">
                <button type="button" disabled={disabled || adding} onClick={() => setAdding(true)} className={buttonClass}>行動を追加</button>
                <button type="button" disabled={disabled || adding} onClick={processDue} className={buttonClass}>期限が到来した行動を処理</button>
                <button type="button" disabled={mutation.busy || resource.loading || adding} onClick={resource.reload} className={buttonClass}>再読み込み</button>
            </div>
        </div>
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {processed && <div role="status" className="space-y-2 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 text-sm">
            <p>処理対象：{processed.length}件 ／ 実行済み：{processed.filter((row) => row.status === 'applied').length}件 ／ 失敗：{processed.filter((row) => row.status === 'failed').length}件</p>
            {processed.map((row) => <p key={row.id} className={row.status === 'failed' ? 'text-[var(--studio-danger)]' : ''}>#{row.id} {row.description || KINDS[row.kind]}（予定：{row.target_period || '未設定'}）— {STATES[row.status]}{typeof row.result.error === 'string' && `：${row.result.error}`}</p>)}
            {!processed.length && <p className="text-[var(--studio-text-muted)]">期限が到来した行動はありませんでした。</p>}
        </div>}
        {adding && <ActionEditor sourcePeriod={sourcePeriod} currency={currency} busy={disabled} onSave={save} onCancel={() => setAdding(false)} />}
        {resource.data && <DataTable columns={['行動', '予定', '関連する予算', '状態', '操作']}>
            {resource.data.length ? resource.data.map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-medium">{row.description || KINDS[row.kind] || row.kind}<span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{KINDS[row.kind] || row.kind}・#{row.id}</span></th>
                <td className="whitespace-nowrap px-5 py-3">{row.target_period || '未設定'}</td>
                <td className="px-5 py-3"><RelatedBudget action={row} currency={currency} /></td>
                <td className="px-5 py-3">{STATES[row.status]}{typeof row.result.error === 'string' && <p className="mt-1 text-xs text-[var(--studio-danger)]">{row.result.error}</p>}</td>
                <td className="px-5 py-3">{row.status === 'pending' ? <div className="flex gap-2">
                    <button type="button" disabled={disabled || adding} onClick={() => decide(row, true)} aria-label={`${row.description}を実行`} className={buttonClass}>実行</button>
                    <button type="button" disabled={disabled || adding} onClick={() => decide(row, false)} aria-label={`${row.description}を見送り`} className={buttonClass}>見送り</button>
                </div> : '—'}</td>
            </tr>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">この月に記録した行動はありません。</td></tr>}
        </DataTable>}
    </div>;
}

export default function Actions() {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const [sourcePeriodEdit, setSourcePeriod] = useState<string | null>(null);
    const sourcePeriod = sourcePeriodEdit ?? clientToday(timezone).slice(0, 7);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <section className="space-y-4">
        <MonthPicker value={sourcePeriod} onChange={setSourcePeriod} />
        <MonthlyActions key={`${clientId}:${sourcePeriod}:${currency}`} sourcePeriod={sourcePeriod} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />
    </section>;
}
