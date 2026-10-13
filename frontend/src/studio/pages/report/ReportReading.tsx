import { useConfirm } from '../../components/useConfirm';
import { Link } from 'react-router-dom';
import type { ActionProposal, MonthlyReport } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';

export interface ProfitLoss {
    total_income: number;
    total_expenses: number;
    net_profit_loss: number;
}

const KINDS: Record<ActionProposal['kind'], string> = {
    allocate_to_goal: '余剰をゴールへ配分', transfer_to_capsule: '取り置きへ移動',
    increase_savings: '積立額を増やす', review_budget: '予算を見直す', extend_target_date: '目標日を延ばす',
};
const STATES = { pending: '未適用', applied: '適用済み', skipped: '見送り', failed: '適用に失敗' };

export function ReportFigures({ report, profitLoss, currency }: { report: MonthlyReport; profitLoss?: ProfitLoss | null; currency: string }) {
    const summary = report.summary;
    const figures = [
        { label: '収入', value: profitLoss ? formatCurrency(profitLoss.total_income, currency) : '—' },
        { label: '支出', value: profitLoss ? formatCurrency(profitLoss.total_expenses, currency) : '—' },
        { label: '収支（収入 − 支出）', value: formatCurrency(summary.period_pl ?? summary.monthly_pl, currency) },
        { label: '期末の純資産', value: formatCurrency(summary.net_worth, currency) },
        { label: '期間中の純資産の増減', value: summary.net_worth_change == null ? '—' : formatCurrency(summary.net_worth_change, currency) },
        { label: '収入に対する収支の割合', value: profitLoss?.total_income === 0 ? '—' : `${summary.savings_rate.toLocaleString('ja-JP', { maximumFractionDigits: 1 })}%` },
    ];
    return <dl className="grid gap-x-6 gap-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 sm:grid-cols-2 xl:grid-cols-3">
        {figures.map((figure) => <div key={figure.label}><dt className="text-xs text-[var(--studio-text-muted)]">{figure.label}</dt><dd className="mt-2 text-xl font-semibold tabular-nums">{figure.value}</dd></div>)}
    </dl>;
}

export function ReportContext({ report, currency }: { report: MonthlyReport; currency: string }) {
    return <details>
        <summary className="cursor-pointer text-sm text-[var(--studio-accent)]">支出の注意点・ゴールの進捗</summary>
        <div className="mt-4 grid gap-6 md:grid-cols-2">
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">支出で確認したいこと</h3>
            {report.anomalies.length ? <ul className="space-y-3">{report.anomalies.map((row: Record<string, unknown>, index) => <li key={index} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                <p className="font-medium">{typeof row.category === 'string' ? row.category : '分類未設定'}</p>
                <p className="mt-2 text-[var(--studio-text-muted)]">計画 {typeof row.budget === 'number' ? formatCurrency(row.budget, currency) : '—'} に対して、実績 {typeof row.actual === 'number' ? formatCurrency(row.actual, currency) : '—'}。</p>
            </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">レポートが挙げる支出の注意点はありません。</p>}
        </section>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">ゴールの進捗</h3>
            {report.goal_progress.length ? <ul className="space-y-3">{report.goal_progress.map((row, index) => <li key={typeof row.id === 'number' ? row.id : index} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                <p className="font-medium">{typeof row.name === 'string' ? row.name : 'ゴール'}</p>
                <p className="mt-2 text-[var(--studio-text-muted)]">見込み進捗 {typeof row.probability_current === 'number' ? `${row.probability_current}%` : '—'} ／ 期間中の変化 {typeof row.delta === 'number' ? `${row.delta > 0 ? '+' : ''}${row.delta}ポイント` : '—'}</p>
            </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">この期間のゴールはありません。</p>}
        </section>
        </div>
    </details>;
}

export function ReportProposals({ report, currency, clientName, disabled, apply, onApplied, onBusy }: {
    report: MonthlyReport; currency: string; clientName?: string; disabled: boolean;
    apply: (proposalId: string) => Promise<unknown>; onApplied: () => void; onBusy: (busy: boolean) => void;
}) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const effect = (proposal: ActionProposal) => {
        const targetId = proposal.target_life_event_id ?? proposal.target_id;
        const goal = report.goal_progress.find((row) => row.id === targetId);
        const target = typeof goal?.name === 'string' ? goal.name : `ゴール #${targetId}`;
        // This action creates today's journal transfer and assigns the savings leg to the goal's capsule.
        if (proposal.kind === 'allocate_to_goal') return `本日付で「cash」から「savings」へ ${formatCurrency(proposal.amount, currency)}（${currency}）を移し、「${target}」の取り置きへ配分します。必要な口座・取り置きがない場合は作成します。`;
        if (proposal.kind === 'review_budget') {
            // Backend descriptions hard-code JPY, so rebuild the reading from its numeric amount and category.
            const anomaly = report.anomalies.find((row: Record<string, unknown>) => typeof row.category === 'string' && proposal.description.startsWith(`${row.category} spending `));
            const category: unknown = anomaly?.category;
            return `${typeof category === 'string' ? `「${category}」の` : ''}次の期間の予算と支出を見直す提案です。見直し額：${formatCurrency(proposal.amount, currency)}（${currency}）。`;
        }
        return proposal.description;
    };
    const run = async (proposal: ActionProposal) => {
        if (disabled || mutation.busy || !clientName || !proposal.auto_executable || proposal.applied || proposal.action_status === 'applied') return;
        if (!(await confirm(`「${clientName}」のレポート（${report.period}）の提案を適用しますか？\n${effect(proposal)}`, "適用する"))) return;
        onBusy(true);
        void mutation.run(() => apply(proposal.id), '提案を適用しました。', onApplied).finally(() => onBusy(false));
    };
    return <details className="space-y-3">
        <summary className="cursor-pointer text-base font-semibold">次にできること</summary>
        <Feedback error={mutation.error} message={mutation.message} />
        {report.action_proposals.length ? <ul className="space-y-3">{report.action_proposals.map((proposal) => <li key={proposal.id} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <div className="flex flex-wrap items-center justify-between gap-3"><h4 className="text-sm font-semibold">{KINDS[proposal.kind]}</h4><span className="text-xs text-[var(--studio-text-muted)]">{proposal.applied ? '適用済み' : STATES[proposal.action_status ?? 'pending']}</span></div>
            <p className="text-sm leading-relaxed text-[var(--studio-text-muted)]">{effect(proposal)}</p>
            {proposal.auto_executable ? <button type="button" className={buttonClass} disabled={disabled || mutation.busy || !clientName || proposal.applied || proposal.action_status === 'applied'} onClick={() => run(proposal)}>この提案を適用</button>
                : <Link to="/budget" className="text-sm text-[var(--studio-accent)] underline">予算で検討する</Link>}
        </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">この期間の提案はありません。</p>}
    </details>;
}
