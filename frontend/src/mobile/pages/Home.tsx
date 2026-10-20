import { useCallback } from 'react';
import { Bot, CheckCircle2, Clock3, Inbox } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getAiChangeRequests, getBalanceSheet, getLifeEventsWithProgress, getTransactionProposals, getTransactionsPage } from '../../api';
import { planCheck } from '../../api/goalPlan';
import { useClient } from '../../context/ClientContext';
import type { Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';
import { useNotifications } from '../../studio/notificationContext';
import { clientToday, useTimezone } from '../../studio/datetime';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { monthLabel } from '../months';
import { useRecording } from '../components/recording';
import { TransactionRow } from '../components/transactions';
import { Card, CardTitle, Empty, ErrorNote, List, Money, ProgressBar, Row, Skeleton } from '../components/ui';
import { accountTypes, loadMonth, totals } from '../data';

interface BalanceSheet { total_assets: number; total_liabilities: number; net_worth: number; assets: Array<{ name: string; balance: number }> }

/** 純資産, this month's spending against the plan, what waits for the user, the goal, the latest records. */
export default function Home() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const period = clientToday(timezone).slice(0, 7);
    const navigate = useNavigate();
    const { open } = useRecording();
    const { items } = useNotifications();
    const loadWorth = useCallback(() => getBalanceSheet() as Promise<BalanceSheet>, []);
    const loadPlan = useCallback(() => loadMonth(period), [period]);
    const loadWaiting = useCallback(async () => {
        const [proposals, requests] = await Promise.all([getTransactionProposals({ status: 'pending' }), getAiChangeRequests({ status: 'pending' })]);
        return { proposals: proposals.length, requests: requests.length };
    }, []);
    const loadGoal = useCallback(async () => {
        const [events, check] = await Promise.all([getLifeEventsWithProgress(), planCheck(period)]);
        const expenses = events.filter((event) => event.direction === 'expense');
        return { required: expenses.reduce((sum, event) => sum + (event.target_amount ?? 0), 0), funded: expenses.reduce((sum, event) => sum + event.current_funded, 0), check };
    }, [period]);
    const loadRecent = useCallback(() => getTransactionsPage({ limit: 5, offset: 0 }), []);
    const worth = useResource(loadWorth);
    const plan = useResource(loadPlan);
    const waiting = useResource(loadWaiting);
    const goal = useResource(loadGoal);
    const recent = useResource(loadRecent);
    const spending = plan.data ? totals(plan.data.model, 'expense') : null;
    const income = plan.data ? totals(plan.data.model, 'income') : null;
    const types = plan.data ? accountTypes(plan.data.accounts) : new Map();
    const tasks = !waiting.data ? [] : [
        { show: (waiting.data?.proposals ?? 0) > 0, icon: Clock3, title: `未反映の自動取引 ${waiting.data?.proposals}件`, to: '/ledger?pending=1' },
        { show: (waiting.data?.requests ?? 0) > 0, icon: Bot, title: `AI からの変更の承認待ち ${waiting.data?.requests}件`, to: '/approvals' },
        { show: items.length > 0, icon: Inbox, title: `通知 ${items.length}件`, to: '/notifications' },
    ].filter((task) => task.show);
    return <Screen title="ホーム" top>
        <section aria-label="純資産" className="rounded-3xl bg-[image:var(--mobile-hero)] p-5 text-white shadow-[var(--mobile-shadow-raised)]">
            <p className="text-xs font-medium text-white/70">純資産</p>
            {worth.data ? <>
                <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight">{formatCurrency(worth.data.net_worth, currency)}</p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                    <button type="button" onClick={() => navigate('/accounts')} className="rounded-2xl bg-white/10 px-3 py-2 text-left active:bg-white/20">
                        <span className="block text-white/70">資産</span><span className="mt-0.5 block text-sm font-semibold tabular-nums">{formatCurrency(worth.data.total_assets, currency)}</span>
                    </button>
                    <button type="button" onClick={() => navigate('/accounts')} className="rounded-2xl bg-white/10 px-3 py-2 text-left active:bg-white/20">
                        <span className="block text-white/70">負債</span><span className="mt-0.5 block text-sm font-semibold tabular-nums">{formatCurrency(worth.data.total_liabilities, currency)}</span>
                    </button>
                </div>
            </> : worth.error ? <p className="mt-2 text-sm">{worth.error}</p> : <div className="mt-2 h-9 w-48 animate-pulse rounded-lg bg-white/20" />}
        </section>

        <Card>
            <CardTitle to="/plan" action="計画">{monthLabel(period)}の収支</CardTitle>
            {plan.error && <ErrorNote message={plan.error} onRetry={plan.reload} />}
            {!plan.data && !plan.error && <div className="h-20 animate-pulse rounded-xl bg-[var(--studio-bg)]" />}
            {spending && income && <div className="space-y-4">
                <div className="space-y-1.5">
                    <div className="flex items-baseline justify-between text-sm"><span className="text-[var(--studio-text-muted)]">支出</span>
                        <span><Money value={spending.actual} currency={currency} className="text-base font-semibold" />{spending.budget > 0 && <span className="text-xs text-[var(--studio-text-muted)]"> / {formatCurrency(spending.budget, currency)}</span>}</span></div>
                    <ProgressBar label="支出の予算の消化" value={spending.actual} max={spending.budget} />
                    {spending.budget > 0 && <p className="text-right text-xs text-[var(--studio-text-muted)]">{spending.actual <= spending.budget ? `残り ${formatCurrency(spending.budget - spending.actual, currency)}` : `${formatCurrency(spending.actual - spending.budget, currency)} 超過`}</p>}
                </div>
                <div className="flex items-baseline justify-between text-sm"><span className="text-[var(--studio-text-muted)]">収入</span>
                    <span><Money value={income.actual} currency={currency} className="font-semibold text-[var(--studio-positive)]" />{income.budget > 0 && <span className="text-xs text-[var(--studio-text-muted)]"> / {formatCurrency(income.budget, currency)}</span>}</span></div>
            </div>}
        </Card>

        <List title="やること">
            {waiting.error ? <Row onClick={waiting.reload} title={<span className="text-[var(--studio-danger)]">確認できませんでした（タップで再読み込み）</span>} chevron={false} />
            : !waiting.data ? <Row title={<span className="text-[var(--studio-text-muted)]">確認しています…</span>} chevron={false} />
            : tasks.length ? tasks.map(({ icon: Icon, title, to }) => <Row key={to} to={to} title={<span className="flex items-center gap-2"><Icon size={16} className="text-[var(--studio-warning)]" aria-hidden />{title}</span>} />)
                : <Row title={<span className="flex items-center gap-2 text-[var(--studio-text-muted)]"><CheckCircle2 size={16} className="text-[var(--studio-positive)]" aria-hidden />やることはありません</span>} />}
        </List>

        <Card>
            <CardTitle to="/goals" action="ゴール">ゴール</CardTitle>
            {goal.error && <ErrorNote message={goal.error} onRetry={goal.reload} />}
            {goal.data && (goal.data.check.goal ? <div className="space-y-3">
                <div className="flex items-baseline justify-between text-sm"><span className="text-[var(--studio-text-muted)]">確保額 / 必要額</span>
                    <span><Money value={goal.data.funded} currency={currency} className="font-semibold" /><span className="text-xs text-[var(--studio-text-muted)]"> / {formatCurrency(goal.data.required, currency)}</span></span></div>
                <ProgressBar label="ゴールの確保" value={goal.data.funded} max={goal.data.required} tone="positive" />
                <div className="flex justify-between text-xs text-[var(--studio-text-muted)]"><span>今月の積立設定 {formatCurrency(goal.data.check.contribution, currency)}</span><span>計画 {formatCurrency(goal.data.check.planned, currency)}</span></div>
            </div> : <p className="text-sm text-[var(--studio-text-muted)]">ゴールのシナリオはまだありません。</p>)}
            {!goal.data && !goal.error && <div className="h-16 animate-pulse rounded-xl bg-[var(--studio-bg)]" />}
        </Card>

        <section>
            <div className="mb-2 flex items-center justify-between px-1"><h2 className="text-xs font-semibold tracking-wide text-[var(--studio-text-muted)]">最近の記録</h2>
                <button type="button" onClick={() => navigate('/ledger')} className="min-h-11 px-1 text-xs font-medium text-[var(--studio-accent)]">家計簿へ</button></div>
            {recent.error && <ErrorNote message={recent.error} onRetry={recent.reload} />}
            {!recent.data && !recent.error && <Skeleton lines={2} />}
            {recent.data && (recent.data.items.length
                ? <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
                    {recent.data.items.map((transaction: Transaction) => <TransactionRow key={transaction.id} transaction={transaction} types={types} currency={currency} onOpen={open} />)}
                </div>
                : <Empty title="まだ記録がありません" body="下の ＋ から最初の取引を記録しましょう。" />)}
        </section>
    </Screen>;
}
