import { Link } from 'react-router-dom';
import type { MonthlyReport } from '../../../types';
import { KINDS, proposalEffect, reportFigures, reportGoals, reportWarnings } from './reportPresentation';
import { tr } from '../../i18n';

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
        {standalone ? <h2 className="text-lg font-semibold">{tr('支出の注意点・ライフイベントの進捗', 'Spending notes and life event progress')}</h2> : <summary className="cursor-pointer text-sm text-[var(--studio-accent)]">{tr('支出の注意点・ライフイベントの進捗', 'Spending notes and life event progress')}</summary>}
        <div className="mt-4 grid gap-6 md:grid-cols-2">
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">{tr('支出で確認したいこと', 'Spending to check')}</h3>
            {report.anomalies.length ? <ul className="space-y-3">{reportWarnings(report, currency).map((row, index) => <li key={index} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                <p className="font-medium">{row.title}</p>
                <p className="mt-2 text-[var(--studio-text-muted)]">{row.description}</p>
            </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">{tr('レポートが挙げる支出の注意点はありません。', 'The report notes nothing about spending.')}</p>}
        </section>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">{tr('ライフイベントの進捗', 'Life event progress')}</h3>
            {report.goal_progress.length ? <ul className="space-y-3">{reportGoals(report).map((row, index) => <li key={index} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                <p className="font-medium">{row.title}</p>
                <p className="mt-2 text-[var(--studio-text-muted)]">{row.description}</p>
            </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">{tr('この期間のライフイベントはありません。', 'No life events in this period.')}</p>}
        </section>
        </div>
    </Container>;
}

/** 次にできること: the report's suggestions; acting on them happens on the plan page. */
export function ReportProposals({ report, currency, standalone = false, readOnly = false }: {
    report: MonthlyReport; currency: string; standalone?: boolean; readOnly?: boolean;
}) {
    const Container = standalone ? 'section' : 'details';
    return <Container className={standalone ? 'space-y-4' : 'space-y-3'}>
        {standalone ? <h2 className="text-lg font-semibold">{tr('次にできること', 'What you can do next')}</h2> : <summary className="cursor-pointer text-base font-semibold">{tr('次にできること', 'What you can do next')}</summary>}
        {report.action_proposals.length ? <ul className="space-y-3">{report.action_proposals.map((proposal) => <li key={proposal.id} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <h4 className="text-sm font-semibold">{KINDS[proposal.kind]}</h4>
            <p className="text-sm leading-relaxed text-[var(--studio-text-muted)]">{proposalEffect(proposal, report, currency)}</p>
            {!readOnly && <div className={`studio-print-hide ${standalone ? 'flex justify-end' : ''}`}><Link to="/plan" className="text-sm text-[var(--studio-accent)] underline">{tr('計画で検討する', 'Consider it in the plan')}</Link></div>}
        </li>)}</ul> : <p className="text-sm text-[var(--studio-text-muted)]">{tr('この期間の提案はありません。', 'No suggestions for this period.')}</p>}
    </Container>;
}
