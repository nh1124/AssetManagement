import { useCallback, useState } from 'react';
import { getGoalCapsules, getLifeEventsWithProgress, getMilestones } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import Scenarios from './Scenarios';

const loadGoals = (): Promise<LifeEvent[]> => getLifeEventsWithProgress();
const PLAN_STATES: Record<string, string> = { Ahead: '計画より先行', 'On Track': '計画どおり', Watch: '要注意', Behind: '計画より遅れ', 'No Plan': '計画なし' };
const percent = (value: number) => new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value);

function GoalDetail({ goal, currency, clientName, onAdopted, onBusy }: {
    goal: LifeEvent; currency: string; clientName?: string; onAdopted: () => void; onBusy: (busy: boolean) => void;
}) {
    const loadMilestones = useCallback(() => getMilestones(goal.id), [goal.id]);
    const loadCapsules = useCallback(() => getGoalCapsules(goal.id), [goal.id]);
    const milestones = useResource(loadMilestones);
    const capsules = useResource(loadCapsules);
    const [busy, setBusy] = useState(false);
    return <section aria-label={`${goal.name}の詳細`} className="space-y-6 border-t border-[var(--studio-border)] pt-6">
        <h2 className="text-lg font-semibold">{goal.name}</h2>
        <section className="space-y-3">
            <div className="flex items-center justify-between gap-3"><h3 className="text-base font-semibold">マイルストーン</h3><button type="button" disabled={busy || milestones.loading} onClick={milestones.reload} className={buttonClass}>再読み込み</button></div>
            <Feedback loading={milestones.loading} error={milestones.error} />
            {milestones.data && <DataTable columns={['予定日', '計画額', '採用状態']}>
                {milestones.data.length ? [...milestones.data].sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id).map((row) => <tr key={row.id}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-normal">{row.date}</th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.target_amount, currency)}</td>
                    <td className="px-5 py-3">{row.is_active_plan === false ? '参考' : '採用中'}</td>
                </tr>) : <tr><td colSpan={3} className="px-5 py-4 text-[var(--studio-text-muted)]">マイルストーンはありません。</td></tr>}
            </DataTable>}
        </section>
        <section className="space-y-3">
            <div className="flex items-center justify-between gap-3"><h3 className="text-base font-semibold">このゴールの取り置き</h3><button type="button" disabled={busy || capsules.loading} onClick={capsules.reload} className={buttonClass}>再読み込み</button></div>
            <Feedback loading={capsules.loading} error={capsules.error} />
            {capsules.data && <DataTable columns={['取り置き', '現在の確保額']}>
                {capsules.data.length ? capsules.data.map((row) => <tr key={row.id}><th scope="row" className="px-5 py-3 font-medium">{row.name}</th><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.current_balance, currency)}</td></tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">このゴールの取り置きはありません。</td></tr>}
            </DataTable>}
        </section>
        <Scenarios goal={goal} currency={currency} clientName={clientName} onBusy={(value) => { setBusy(value); onBusy(value); }} onAdopted={() => { milestones.reload(); onAdopted(); }} />
    </section>;
}

function GoalsForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const resource = useResource(loadGoals);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [busy, setBusy] = useState(false);
    const [detailRevision, setDetailRevision] = useState(0);
    const selected = resource.data?.find((goal) => goal.id === selectedId);
    const refresh = () => {
        resource.reload();
        // A refreshed goal or assumption list invalidates every earlier preview.
        setDetailRevision((value) => value + 1);
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-lg font-semibold">ゴール</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">対象：{clientName || 'クライアントを確認中…'} ／ 表示通貨：{currency}。ゴールを選ぶと、計画案を比較・採用できます。</p></div>
            <button type="button" disabled={resource.loading || busy} onClick={refresh} className={buttonClass}>再読み込み</button>
        </div>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <DataTable columns={['名称', '目標額', '目標日', '現在の確保額', '進捗', '計画の状態']}>
            {resource.data.length ? resource.data.map((goal) => <tr key={goal.id} className={goal.id === selectedId ? 'bg-[var(--studio-accent-soft)]' : ''}>
                <th scope="row" className="px-5 py-3 font-medium"><button type="button" disabled={resource.loading || Boolean(resource.error) || busy} onClick={() => setSelectedId(goal.id)} aria-expanded={goal.id === selectedId} aria-controls={goal.id === selectedId ? 'selected-goal-detail' : undefined} className="rounded text-left text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{goal.name}</button></th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(goal.target_amount, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{goal.target_date}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.current_funded == null ? '—' : formatCurrency(goal.current_funded, currency)}</td>
                {/* funded_percentage measures secured money; progress_percentage is a projection. */}
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.funded_percentage == null ? '—' : `${percent(goal.funded_percentage)}%`}</td>
                <td className="whitespace-nowrap px-5 py-3">{goal.plan_status ? PLAN_STATES[goal.plan_status] || goal.plan_status : '—'}</td>
            </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">ゴールはありません。</td></tr>}
        </DataTable>}
        {selected && <div id="selected-goal-detail"><GoalDetail key={`${selected.id}:${detailRevision}`} goal={selected} currency={currency} clientName={clientName} onBusy={setBusy} onAdopted={resource.reload} /></div>}
    </section>;
}

export default function Goals() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Client and currency changes discard previews before any write can reuse them.
    return <GoalsForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
