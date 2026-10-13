import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useCallback, useState } from 'react';
import { archiveGoal, getGoalCapsules, getLifeEventsWithProgress, unarchiveGoal } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';
import GoalDeletion from './GoalDeletion';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import Milestones from './Milestones';
import Scenarios from './Scenarios';

const PLAN_STATES: Record<string, string> = { Ahead: '計画より先行', 'On Track': '計画どおり', Watch: '要注意', Behind: '計画より遅れ', 'No Plan': '計画なし' };
const percent = (value: number) => new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value);

function GoalDetail({ goal, currency, clientName, onChanged, onBusy }: {
    goal: LifeEvent; currency: string; clientName?: string; onChanged: () => void; onBusy: (busy: boolean) => void;
}) {
    const loadCapsules = useCallback(() => getGoalCapsules(goal.id), [goal.id]);
    const capsules = useResource(loadCapsules);
    const [busy, setBusy] = useState(false);
    const [milestoneRevision, setMilestoneRevision] = useState(0);
    const [scenarioRevision, setScenarioRevision] = useState(0);
    const lock = (value: boolean) => { setBusy(value); onBusy(value); };
    return <section aria-label={`${goal.name}の詳細`} className="space-y-6 border-t border-[var(--studio-border)] pt-6">
        <h2 className="text-lg font-semibold">{goal.name}{goal.archived_at && '（中止・アーカイブ）'}</h2>
        <p className="text-sm text-[var(--studio-text-muted)]">開始日：{goal.start_date || '未設定'} ／ 優先度：{goal.priority === 1 ? '高' : goal.priority === 2 ? '中' : '低'}{goal.note && ` ／ ${goal.note}`}</p>
        <Milestones key={milestoneRevision} goalId={goal.id} currency={currency} disabled={busy || !clientName} onBusy={lock} onChanged={() => { setScenarioRevision((value) => value + 1); onChanged(); }} />
        <section className="space-y-3">
            <div className="flex items-center justify-between gap-3"><h3 className="text-base font-semibold">このゴールの取り置き</h3><button type="button" disabled={busy || capsules.loading} onClick={capsules.reload} className={buttonClass}>再読み込み</button></div>
            <Feedback loading={capsules.loading} error={capsules.error} />
            {capsules.data && <DataTable columns={['取り置き', '現在の確保額']}>
                {capsules.data.length ? capsules.data.map((row) => <tr key={row.id}><th scope="row" className="px-5 py-3 font-medium">{row.name}</th><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.current_balance, currency)}</td></tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">このゴールの取り置きはありません。</td></tr>}
            </DataTable>}
        </section>
        {/* Manual changes invalidate scenario previews because adoption replaces the same rows. */}
        <fieldset disabled={busy || Boolean(goal.archived_at)} className="min-w-0">
            <Scenarios key={scenarioRevision} goal={goal} currency={currency} clientName={clientName} onBusy={lock} onAdopted={() => { setMilestoneRevision((value) => value + 1); onChanged(); }} />
        </fieldset>
    </section>;
}

function GoalsForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const confirm = useConfirm();
    const navigate = useNavigate();
    const location = useLocation();
    const [search, setSearch] = useSearchParams();
    const includeArchived = search.get('archived') === 'true';
    const setIncludeArchived = (value: boolean) => setSearch((previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set('archived', 'true'); else next.delete('archived');
        return next;
    }, { replace: true });
    const edit = (path: string) => navigate(path, { state: { returnTo: location.pathname + location.search } });
    const load = useCallback(() => getLifeEventsWithProgress(includeArchived), [includeArchived]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [detailBusy, setDetailBusy] = useState(false);
    const [detailRevision, setDetailRevision] = useState(0);
    const [deleting, setDeleting] = useState<LifeEvent | null>(null);
    const selected = resource.data?.find((goal) => goal.id === selectedId);
    const busy = detailBusy || mutation.busy;
    const disabled = busy || resource.loading || Boolean(resource.error) || !clientName;
    const refresh = () => {
        resource.reload();
        // A refreshed goal or assumption list invalidates every earlier preview.
        setDetailRevision((value) => value + 1);
    };
    const run = (action: () => Promise<unknown>, message: string) => {
        if (disabled) return;
        void mutation.run(action, message, () => { setDeleting(null); refresh(); });
    };
    const archive = async (goal: LifeEvent) => {
        if (!(await confirm(`「${clientName}」のゴール「${goal.name}」を中止しますか？\n取り置きと積み立てたお金・履歴はそのまま残ります。ゴールはアーカイブから戻せます。`, '中止する'))) return;
        run(() => archiveGoal(goal.id), `「${goal.name}」を中止しました。取り置きの貯蓄はそのままです。`);
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-lg font-semibold">ゴール</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">対象：{clientName || 'クライアントを確認中…'} ／ 表示通貨：{currency}。ゴールを選ぶと、計画案を比較・採用できます。</p></div>
            <div className="flex gap-2"><button type="button" disabled={disabled || deleting !== null} onClick={() => edit('/goals/new')} className={buttonClass}>新しいゴール</button><button type="button" disabled={resource.loading || busy || deleting !== null} onClick={refresh} className={buttonClass}>再読み込み</button></div>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeArchived} disabled={busy || deleting !== null} onChange={(event) => { setIncludeArchived(event.target.checked); setSelectedId(null); resource.reload(); }} />アーカイブを表示</label>
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {deleting && clientName && <Overlay title={`「${deleting.name}」を削除`} onClose={() => setDeleting(null)}><Feedback error={mutation.error} /><GoalDeletion goal={deleting} currency={currency} clientName={clientName} busy={disabled} onCancel={() => setDeleting(null)} onDelete={(action) => run(action, 'ゴールを削除しました。')} /></Overlay>}
        {resource.data && <DataTable columns={['名称', '目標額', '目標日', '現在の確保額', '進捗', '計画の状態', '操作']}>
            {resource.data.length ? resource.data.map((goal) => <tr key={goal.id} className={goal.id === selectedId ? 'bg-[var(--studio-accent-soft)]' : ''}>
                <th scope="row" className="px-5 py-3 font-medium"><button type="button" disabled={disabled || deleting !== null} onClick={() => setSelectedId(goal.id)} aria-expanded={goal.id === selectedId} className="rounded text-left text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{goal.name}</button></th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(goal.target_amount, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{goal.target_date}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.current_funded == null ? '—' : formatCurrency(goal.current_funded, currency)}</td>
                {/* funded_percentage measures secured money; progress_percentage is a projection. */}
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.funded_percentage == null ? '—' : `${percent(goal.funded_percentage)}%`}</td>
                <td className="whitespace-nowrap px-5 py-3">{goal.archived_at ? '中止・アーカイブ' : goal.plan_status ? PLAN_STATES[goal.plan_status] || goal.plan_status : '—'}</td>
                <td className="px-5 py-3"><div className="flex gap-2 whitespace-nowrap">
                    <button type="button" disabled={disabled || deleting !== null} onClick={() => edit(`/goals/${goal.id}/edit`)} className={buttonClass}>編集</button>
                    {goal.archived_at ? <button type="button" disabled={disabled || deleting !== null} onClick={() => run(() => unarchiveGoal(goal.id), `「${goal.name}」を戻しました。`)} className={buttonClass}>戻す</button> : <button type="button" disabled={disabled || deleting !== null} onClick={() => archive(goal)} className={buttonClass}>中止する</button>}
                    <button type="button" disabled={disabled || deleting !== null} onClick={() => { setSelectedId(null); setDeleting(goal); }} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>
                </div></td>
            </tr>) : <tr><td colSpan={7} className="px-5 py-4 text-[var(--studio-text-muted)]">ゴールはありません。</td></tr>}
        </DataTable>}
        {selected && !deleting && <GoalDetail key={`${selected.id}:${detailRevision}`} goal={selected} currency={currency} clientName={clientName} onBusy={setDetailBusy} onChanged={resource.reload} />}
    </section>;
}

export default function Goals() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Client and currency changes discard previews before any write can reuse them.
    return <GoalsForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
