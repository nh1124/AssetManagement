import { useEffect, useState } from 'react';
import { Check, Loader2, RefreshCw, SkipForward } from 'lucide-react';
import {
    applyMonthlyReportAction,
    applyReviewAction,
    getMonthlyActions,
    getMonthlyReport,
    skipReviewAction,
} from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { ActionProposal, MonthlyAction, MonthlyReport } from '../../types';
import { formatCurrency } from '../../utils/currency';

export default function MobileReviewPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [report, setReport] = useState<MonthlyReport | null>(null);
    const [actions, setActions] = useState<MonthlyAction[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [busyKey, setBusyKey] = useState<string | null>(null);
    const [selectedMonth, setSelectedMonth] = useState(() => {
        const now = new Date();
        return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    });
    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';

    const loadReview = async () => {
        setIsLoading(true);
        try {
            const [year, month] = selectedMonth.split('-').map(Number);
            const [reportData, actionData] = await Promise.all([
                getMonthlyReport(year, month),
                getMonthlyActions(),
            ]);
            setReport(reportData);
            setActions(actionData.filter((action) => action.status === 'pending').slice(0, 8));
        } catch {
            showToast('Failed to load mobile review', 'error');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadReview();
    }, [selectedMonth]);

    const applyProposal = async (proposal: ActionProposal) => {
        if (!report) return;
        const key = `proposal:${proposal.id}`;
        setBusyKey(key);
        try {
            await applyMonthlyReportAction(report.period, proposal.id);
            showToast('Proposal applied', 'success');
            await loadReview();
        } catch {
            showToast('Failed to apply proposal', 'error');
        } finally {
            setBusyKey(null);
        }
    };

    const processAction = async (action: MonthlyAction, mode: 'apply' | 'skip') => {
        const key = `action:${action.id}:${mode}`;
        setBusyKey(key);
        try {
            if (mode === 'apply') {
                await applyReviewAction(action.id);
                showToast('Action applied', 'success');
            } else {
                await skipReviewAction(action.id);
                showToast('Action skipped', 'info');
            }
            await loadReview();
        } catch {
            showToast(`Failed to ${mode} action`, 'error');
        } finally {
            setBusyKey(null);
        }
    };

    return (
        <div className="space-y-4 p-3">
            <section className="flex items-center justify-between">
                <div>
                    <p className="text-[10px] uppercase tracking-wide text-slate-500">Mobile Review</p>
                    <h1 className="text-xl font-semibold text-slate-50">Monthly Review</h1>
                </div>
                <button
                    type="button"
                    onClick={loadReview}
                    className="flex h-10 w-10 items-center justify-center border border-slate-800 bg-slate-900 text-slate-300"
                    aria-label="Refresh review"
                >
                    <RefreshCw size={17} className={isLoading ? 'animate-spin' : ''} />
                </button>
            </section>

            <label className="block">
                <span className="text-[10px] uppercase tracking-wide text-slate-500">Period</span>
                <input
                    type="month"
                    value={selectedMonth}
                    onChange={(event) => setSelectedMonth(event.target.value)}
                    className="mt-1 h-11 w-full border border-slate-800 bg-slate-900 px-3 text-sm text-slate-100 outline-none focus:border-emerald-500"
                />
            </label>

            {report ? (
                <>
                    <section className="grid grid-cols-2 gap-2">
                        <ReviewMetric label="Net Worth" value={formatCurrency(report.summary.net_worth, currentCurrency)} />
                        <ReviewMetric label="P/L" value={formatCurrency(report.summary.period_pl ?? report.summary.monthly_pl, currentCurrency)} />
                        <ReviewMetric label="Savings" value={`${Math.round((report.summary.savings_rate ?? 0) * 100)}%`} />
                        <ReviewMetric label="Actions" value={String(report.action_proposals?.length ?? 0)} />
                    </section>

                    <section className="space-y-2">
                        <h2 className="text-sm font-medium text-slate-100">Report Proposals</h2>
                        {(report.action_proposals ?? []).length === 0 ? (
                            <EmptyBlock text="No report proposals for this period." />
                        ) : (
                            <div className="space-y-2">
                                {report.action_proposals.map((proposal) => (
                                    <ProposalCard
                                        key={proposal.id}
                                        proposal={proposal}
                                        currency={currentCurrency}
                                        isBusy={busyKey === `proposal:${proposal.id}`}
                                        onApply={() => applyProposal(proposal)}
                                    />
                                ))}
                            </div>
                        )}
                    </section>
                </>
            ) : (
                <EmptyBlock text={isLoading ? 'Loading monthly report...' : 'Monthly report is not available.'} />
            )}

            <section className="space-y-2">
                <h2 className="text-sm font-medium text-slate-100">Pending Actions</h2>
                {actions.length === 0 ? (
                    <EmptyBlock text="No pending review actions." />
                ) : (
                    <div className="space-y-2">
                        {actions.map((action) => (
                            <article key={action.id} className="border border-slate-800 bg-slate-900/70 p-3">
                                <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="truncate text-sm font-medium text-slate-100">{action.kind}</p>
                                        <p className="mt-1 line-clamp-2 text-[10px] text-slate-500">{action.description || action.source_period}</p>
                                    </div>
                                    {action.amount != null && (
                                        <p className="shrink-0 font-mono-nums text-xs text-slate-200">
                                            {formatCurrency(action.amount, currentCurrency)}
                                        </p>
                                    )}
                                </div>
                                <div className="mt-3 grid grid-cols-2 gap-2">
                                    <button
                                        type="button"
                                        onClick={() => processAction(action, 'skip')}
                                        disabled={busyKey !== null}
                                        className="flex h-10 items-center justify-center gap-2 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
                                    >
                                        {busyKey === `action:${action.id}:skip` ? <Loader2 size={14} className="animate-spin" /> : <SkipForward size={14} />}
                                        Skip
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => processAction(action, 'apply')}
                                        disabled={busyKey !== null}
                                        className="flex h-10 items-center justify-center gap-2 bg-emerald-600 text-xs font-medium text-white disabled:opacity-50"
                                    >
                                        {busyKey === `action:${action.id}:apply` ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                                        Apply
                                    </button>
                                </div>
                            </article>
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}

function ReviewMetric({ label, value }: { label: string; value: string }) {
    return (
        <div className="border border-slate-800 bg-slate-900/70 p-3">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
            <p className="mt-2 truncate font-mono-nums text-sm text-slate-100">{value}</p>
        </div>
    );
}

function ProposalCard({
    proposal,
    currency,
    isBusy,
    onApply,
}: {
    proposal: ActionProposal;
    currency: string;
    isBusy: boolean;
    onApply: () => void;
}) {
    const isDone = proposal.action_status === 'applied' || proposal.applied;
    return (
        <article className="border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{proposal.kind}</p>
                    <p className="mt-1 line-clamp-3 text-[10px] text-slate-500">{proposal.description}</p>
                </div>
                {proposal.amount != null && (
                    <p className="shrink-0 font-mono-nums text-xs text-slate-200">{formatCurrency(proposal.amount, currency)}</p>
                )}
            </div>
            <button
                type="button"
                onClick={onApply}
                disabled={isBusy || isDone || !proposal.auto_executable}
                className="mt-3 flex h-10 w-full items-center justify-center gap-2 bg-emerald-600 text-xs font-medium text-white disabled:bg-slate-800 disabled:text-slate-500"
            >
                {isBusy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                {isDone ? 'Applied' : proposal.auto_executable ? 'Apply Proposal' : 'Review on desktop'}
            </button>
        </article>
    );
}

function EmptyBlock({ text }: { text: string }) {
    return (
        <div className="border border-dashed border-slate-800 bg-slate-900/40 px-3 py-5 text-sm text-slate-500">
            {text}
        </div>
    );
}
