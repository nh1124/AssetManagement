import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getGoalCapsules, getRoadmapProjection, unarchiveGoal } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { formatDate } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { ACCOUNT_TYPES, buttonClass, loadAccounts, useMutation } from '../db/forms';
import GoalArchive from './GoalArchive';
import GoalCapsuleLinks from './GoalCapsuleLinks';
import GoalConditions from './GoalConditions';
import GoalDeletion from './GoalDeletion';
import GoalEditor from './GoalEditor';
import GoalProjection from './GoalProjection';
import Milestones from './Milestones';
import Scenarios from './Scenarios';
import { capsuleClaims, goalPercent, goalPlanStatus } from './presentation';

function GoalWorkspaceForClient({ goalId, currency, clientName }: { goalId: string; currency: string; clientName?: string }) {
    const navigate = useNavigate();
    const load = useCallback(async () => {
        if (!/^\d+$/.test(goalId)) throw new Error('このライフイベントは見つかりません。');
        const [roadmap, capsules, accounts] = await Promise.all([
            getRoadmapProjection({ roadmap_interval: 'monthly', include_archived: true }), getGoalCapsules(Number(goalId)), loadAccounts(),
        ]);
        const goal = roadmap.events.find((row) => row.id === Number(goalId));
        if (!goal) throw new Error('このライフイベントは見つかりません。');
        return { goal, roadmap, capsules, accounts };
    }, [goalId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [dialog, setDialog] = useState<'archive' | 'delete' | 'edit' | 'capsules' | null>(null);
    const [monteCarlo, setMonteCarlo] = useState(false);
    const [detailBusy, setDetailBusy] = useState(false);
    const [projectionRevision, setProjectionRevision] = useState(0);
    const [milestoneRevision, setMilestoneRevision] = useState(0);
    const [scenarioRevision, setScenarioRevision] = useState(0);
    const busy = mutation.busy || detailBusy;
    const disabled = busy || resource.loading || Boolean(resource.error) || !clientName;
    const refresh = () => { resource.reload(); setProjectionRevision((value) => value + 1); };
    const run = (action: () => Promise<unknown>, message: string, deleted = false) => {
        if (disabled) return;
        void mutation.run(action, message, () => { setDialog(null); if (deleted) navigate('/goals/events', { replace: true }); else refresh(); });
    };
    const goal = resource.data?.goal;
    const income = goal?.direction === 'income';
    const account = resource.data?.accounts.find((row) => row.id === goal?.account_id);
    const accountLabel = account ? `${account.name}（${ACCOUNT_TYPES[account.account_type]}）` : goal?.account_id != null ? `#${goal.account_id}（一覧にありません）` : '未設定';
    return <section className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><Link to={goal?.archived_at ? '/goals/events?archived=true' : '/goals/events'} className="text-sm text-[var(--studio-accent)] hover:underline">ライフイベント一覧へ</Link><h2 className="mt-2 text-lg font-semibold">{goal?.name ?? 'ライフイベント'}{goal?.archived_at && '（中止・アーカイブ）'}</h2></div>
            {goal && <div className="flex flex-wrap gap-2">
                <button type="button" disabled={disabled || dialog !== null} onClick={() => setDialog('edit')} className={buttonClass}>編集</button>
                {goal.archived_at ? <button type="button" disabled={disabled || dialog !== null} onClick={() => run(() => unarchiveGoal(goal.id), 'ライフイベントを戻しました。停止した規則と戻したお金は、そのままです。')} className={buttonClass}>戻す</button> : <button type="button" disabled={disabled || dialog !== null} onClick={() => setDialog('archive')} className={buttonClass}>中止する</button>}
                <button type="button" disabled={disabled || dialog !== null} onClick={() => setDialog('delete')} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>
            </div>}
        </div>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} message={mutation.message} />
        {goal && resource.data && <>
            <section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">目標日までの推移</h3><div role="group" aria-label="試算方法" className="flex gap-2">
                    <button type="button" disabled={resource.loading} aria-pressed={!monteCarlo} onClick={() => setMonteCarlo(false)} className={`${buttonClass} aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>通常試算</button>
                    <button type="button" disabled={resource.loading} aria-pressed={monteCarlo} onClick={() => setMonteCarlo(true)} className={`${buttonClass} aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>モンテカルロ</button>
                </div></div>
                {!resource.loading && !resource.error && <GoalProjection key={`${projectionRevision}:${monteCarlo}`} goal={goal} roadmap={resource.data.roadmap} currency={currency} monteCarlo={monteCarlo} />}
            </section>
            <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
                {/* Income events are inflows and therefore have no funding need or funding progress. */}
                {[
                    ['種別', income ? '収入' : '支出'], ['口座・科目', accountLabel],
                    [income ? '金額' : '目標額', formatCurrency(goal.target_amount, currency)], ['目標日', formatDate(goal.target_date)],
                    ...(!income ? [['現在の確保額', formatCurrency(goal.current_funded, currency)], ['進捗', goalPercent(goal.funded_percentage)], ['計画の状態', goalPlanStatus(goal)]] : []),
                ].map(([label, value]) => <div key={label}><dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt><dd className="mt-2 font-semibold tabular-nums">{value}</dd></div>)}
            </dl>
            <GoalConditions goalId={goal.id} currency={currency} clientName={clientName} disabled={disabled || dialog !== null} onBusy={setDetailBusy} />
            <details className="rounded-lg border border-[var(--studio-border)] p-5"><summary className="cursor-pointer font-semibold">マイルストーン</summary><div className="mt-5">
                <Milestones key={milestoneRevision} goalId={goal.id} currency={currency} disabled={disabled || dialog !== null || Boolean(goal.archived_at)} onBusy={setDetailBusy} onChanged={() => { setScenarioRevision((value) => value + 1); refresh(); }} />
            </div></details>
            {/* Reservations and funding scenarios only apply to expense events, which need funding. */}
            {!income && <details className="rounded-lg border border-[var(--studio-border)] p-5"><summary className="cursor-pointer font-semibold">取り置き</summary><div className="mt-5 space-y-4">
                <button type="button" disabled={disabled || dialog !== null} onClick={() => setDialog('capsules')} className={buttonClass}>取り置きを紐づける</button>
                <DataTable columns={['取り置き', '現在の確保額（通貨別）']}>
                    {resource.data.capsules.length ? resource.data.capsules.map((row) => <tr key={row.id}><th scope="row" className="px-5 py-3 font-medium">{row.name}</th><td className="px-5 py-3 tabular-nums">{capsuleClaims(row)}</td></tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">このライフイベントの取り置きはありません。</td></tr>}
                </DataTable>
            </div></details>}
            {!income && <details className="rounded-lg border border-[var(--studio-border)] p-5"><summary className="cursor-pointer font-semibold">計画案</summary><fieldset disabled={disabled || dialog !== null || Boolean(goal.archived_at)} className="mt-5 min-w-0">
                <Scenarios key={scenarioRevision} goal={goal} currency={currency} clientName={clientName} onBusy={setDetailBusy} onAdopted={() => { setMilestoneRevision((value) => value + 1); refresh(); }} />
            </fieldset></details>}
            {dialog === 'edit' && <Overlay title={`「${goal.name}」を編集`} onClose={() => { if (!busy) setDialog(null); }}>
                <Feedback error={mutation.error} />
                <GoalEditor goal={goal} currency={currency} embedded busy={disabled} onCancel={() => { if (!busy) setDialog(null); }} onSave={(action) => run(action, 'ライフイベントを保存しました。')} />
            </Overlay>}
            {dialog === 'capsules' && !income && <GoalCapsuleLinks goal={goal} busy={busy} onClose={() => setDialog(null)} onChanged={refresh} onBusy={setDetailBusy} />}
            {dialog === 'archive' && clientName && <GoalArchive goal={goal} clientName={clientName} busy={busy} error={mutation.error} onCancel={() => setDialog(null)} onArchive={(action) => run(action, 'ライフイベントを中止しました。取り置きには選択した処理を適用しました。')} />}
            {dialog === 'delete' && clientName && <Overlay title={`「${goal.name}」を削除`} onClose={() => { if (!busy) setDialog(null); }}><Feedback error={mutation.error} /><GoalDeletion goal={goal} clientName={clientName} busy={disabled} onDelete={(action) => run(action, 'ライフイベントを削除しました。', true)} /></Overlay>}
        </>}
    </section>;
}

export default function GoalWorkspace() {
    const { goalId = '' } = useParams();
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <GoalWorkspaceForClient key={`${clientId}:${currency}:${goalId}`} goalId={goalId} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
