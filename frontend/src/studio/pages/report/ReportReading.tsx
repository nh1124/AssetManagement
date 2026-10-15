import { useConfirm } from '../../components/useConfirm';
import { Link } from 'react-router-dom';
import type { ActionProposal, MonthlyReport } from '../../../types';
import { KINDS, STATES, proposalEffect, reportFigures, reportGoals, reportWarnings } from './reportPresentation';
import { Feedback } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';

export interface ProfitLoss {
    total_income: number;
    total_expenses: number;
    net_profit_loss: number;
}

export function ReportFigures({ report, profitLoss, currency }: { report: MonthlyReport; profitLoss?: ProfitLoss | null; currency: string }) {
    const figures = reportFigures(report, profitLoss, currency);
    return <dl className="grid gap-x-6 gap-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 sm:grid-cols-2 xl:grid-cols-3">
        {figures.map((figure) => <div key={figure.label}><dt className="text-xs text-[var(--studio-text-muted)]">{figure.label}</dt><dd className="mt-2 text-xl font-semibold tabular-nums">{figure.value}</dd></div>)}
    </dl>;
}

export function ReportContext({ report, currency, standalone = false }: { report: MonthlyReport; currency: string; standalone?: boolean }) {
    // Review keeps its disclosure while Breakdown gives each section equal prominence.
    const Container = standalone ? 'section' : 'details';
    return <Container className={standalone ? 'space-y-4' : undefined}>
        {standalone ? <h2 className="text-lg font-semibold">支出の注意点・ライフイベントの進捗</h2> : <summary className="cursor-pointer text-sm text-[var(--studio-accent)]">支出の注意点・ライフイベントの進捗</summary>}
        <div className="mt-4 grid gap-6 md:grid-cols-2">
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">支出で確認したいこと</h3>
            {report.anomalies.length ? <ul className="space-y-3">{reportWarnings(report, currency).map((row, index) => <li key={index} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                <p className="font-medium">{row.title}</p>
                <p className="mt-2 text-[var(--studio-text-muted)]">{row.description}</p>
            </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">レポートが挙げる支出の注意点はありません。</p>}
        </section>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">ライフイベントの進捗</h3>
            {report.goal_progress.length ? <ul className="space-y-3">{reportGoals(report).map((row, index) => <li key={index} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                <p className="font-medium">{row.title}</p>
                <p className="mt-2 text-[var(--studio-text-muted)]">{row.description}</p>
            </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">この期間のライフイベントはありません。</p>}
        </section>
        </div>
    </Container>;
}

export function ReportProposals({ report, currency, clientName, disabled, apply, onApplied, onBusy, standalone = false, readOnly = false }: {
    report: MonthlyReport; currency: string; clientName?: string; disabled: boolean;
    apply: (proposalId: string) => Promise<unknown>; onApplied: () => void; onBusy: (busy: boolean) => void;
    standalone?: boolean; readOnly?: boolean;
}) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const run = async (proposal: ActionProposal) => {
        if (readOnly || disabled || mutation.busy || !clientName || !proposal.auto_executable || proposal.applied || proposal.action_status === 'applied') return;
        if (!(await confirm(`「${clientName}」のレポート（${report.period}）の提案を適用しますか？\n${proposalEffect(proposal, report, currency)}`, "適用する"))) return;
        onBusy(true);
        void mutation.run(() => apply(proposal.id), '提案を適用しました。', onApplied).finally(() => onBusy(false));
    };
    const Container = standalone ? 'section' : 'details';
    return <Container className={standalone ? 'space-y-4' : 'space-y-3'}>
        {standalone ? <h2 className="text-lg font-semibold">次にできること</h2> : <summary className="cursor-pointer text-base font-semibold">次にできること</summary>}
        <Feedback error={mutation.error} message={mutation.message} />
        {report.action_proposals.length ? <ul className="space-y-3">{report.action_proposals.map((proposal) => <li key={proposal.id} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <div className="flex flex-wrap items-center justify-between gap-3"><h4 className="text-sm font-semibold">{KINDS[proposal.kind]}</h4><span className="text-xs text-[var(--studio-text-muted)]">{proposal.applied ? '適用済み' : STATES[proposal.action_status ?? 'pending']}</span></div>
            <p className="text-sm leading-relaxed text-[var(--studio-text-muted)]">{proposalEffect(proposal, report, currency)}</p>
            {!readOnly && <div className={`studio-print-hide ${standalone ? 'flex justify-end' : ''}`}>{proposal.auto_executable ? <button type="button" className={standalone ? primaryClass : buttonClass} disabled={disabled || mutation.busy || !clientName || proposal.applied || proposal.action_status === 'applied'} onClick={() => run(proposal)}>この提案を適用</button>
                : <Link to="/budget" className="text-sm text-[var(--studio-accent)] underline">予算で検討する</Link>}</div>}
        </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">この期間の提案はありません。</p>}
    </Container>;
}
