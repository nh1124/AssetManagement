import { useCallback, useState } from 'react';
import { CalendarDays, ExternalLink, Target } from 'lucide-react';
import { Area, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getLifeEventsWithProgress } from '../../api';
import { planCheck } from '../../api/goalPlan';
import { compare, list, type ProjectedLifeScenario } from '../../api/lifeScenarios';
import { useClient } from '../../context/ClientContext';
import type { LifeEventProgress } from '../../types';
import { formatCurrency, getCurrencySymbol } from '../../utils/currency';
import { clientToday, formatDate, useTimezone } from '../../studio/datetime';
import { scheduleText } from '../../studio/pages/goals/contributionText';
import { eventAmount, KIND_LABELS } from '../../studio/pages/goals/eventKinds';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import Sheet from '../components/Sheet';
import { Badge, Card, Empty, ErrorNote, focusRing, Money, ProgressBar, Skeleton } from '../components/ui';
import { activeLanguage, tr } from '../../studio/i18n';

const percent = (value: number | null | undefined) => value == null ? '—' : `${Math.round(value * 100)}%`;

/** An axis label short enough for a phone: 4500万, 1.2億 in yen; 45k, 1.2M otherwise. */
function axisLabel(value: number, currency: string): string {
    const sign = value < 0 ? '−' : '';
    const size = Math.abs(value);
    const trim = (number: number) => String(Math.round(number * 10) / 10);
    if (currency === 'JPY' && activeLanguage() === 'ja') {
        if (size >= 1e8) return `${sign}${trim(size / 1e8)}億`;
        if (size >= 1e4) return `${sign}${trim(size / 1e4)}万`;
        return `${sign}${Math.round(size)}`;
    }
    const symbol = getCurrencySymbol(currency);
    if (size >= 1e6) return `${sign}${symbol}${trim(size / 1e6)}M`;
    if (size >= 1e3) return `${sign}${symbol}${trim(size / 1e3)}k`;
    return `${sign}${symbol}${Math.round(size)}`;
}

/** Net worth bands and the cumulative need, compact enough for a phone. */
function ProjectionChart({ projected, currency }: { projected: ProjectedLifeScenario; currency: string }) {
    const rows = projected.projection.map((row) => ({ year: row.year, band: [row.p10, row.p90], p50: row.p50, need: row.cumulative_target }));
    return <div role="img" aria-label={tr('純資産の見通し：中央値とP10〜P90の幅、累計必要額', 'Net worth outlook: the median, the P10 to P90 range and the cumulative need')} className="h-56">
        <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
                <XAxis dataKey="year" tick={{ fill: 'var(--studio-text-muted)', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis width={44} tick={{ fill: 'var(--studio-text-muted)', fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(value: number) => axisLabel(value, currency)} />
                <Tooltip formatter={(value) => Array.isArray(value) ? value.map((item) => formatCurrency(Number(item), currency)).join(tr('〜', ' – ')) : formatCurrency(Number(value), currency)}
                    labelFormatter={(label) => tr(`${label}年`, `${label}`)} contentStyle={{ borderRadius: 12, border: '1px solid var(--studio-border)', fontSize: 12 }} />
                <Area dataKey="band" name={tr('P10〜P90', 'P10–P90')} stroke="none" fill="var(--studio-accent)" fillOpacity={0.14} isAnimationActive={false} />
                <Line dataKey="p50" name={tr('中央値', 'Median')} stroke="var(--studio-accent)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
                <Line dataKey="need" name={tr('累計必要額', 'Cumulative need')} stroke="var(--studio-text-muted)" strokeWidth={1.6} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            </ComposedChart>
        </ResponsiveContainer>
    </div>;
}

function EventSheet({ event, outcome, currency, timezone, onClose }: {
    event: LifeEventProgress; outcome?: ProjectedLifeScenario['events'][number]; currency: string; timezone: string; onClose: () => void;
}) {
    const expense = event.direction === 'expense';
    return <Sheet title={event.name} onClose={onClose}>
        <div className="space-y-4">
            <Card>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                    <div><dt className="text-xs text-[var(--studio-text-muted)]">{tr('種別', 'Kind')}</dt><dd className="font-medium">{KIND_LABELS[event.direction]}</dd></div>
                    <div><dt className="text-xs text-[var(--studio-text-muted)]">{tr('日付', 'Date')}</dt><dd className="font-medium">{formatDate(event.target_date, timezone)}</dd></div>
                    <div><dt className="text-xs text-[var(--studio-text-muted)]">{tr('金額', 'Amount')}</dt><dd className="font-medium tabular-nums">{eventAmount(event, currency)}</dd></div>
                    <div><dt className="text-xs text-[var(--studio-text-muted)]">{tr('起きる確率', 'Chance it happens')}</dt><dd className="font-medium">{percent(outcome?.executed_probability)}</dd></div>
                    {expense && <div><dt className="text-xs text-[var(--studio-text-muted)]">{tr('資金が足りる確率', 'Chance it is funded')}</dt><dd className="font-medium">{percent(outcome?.funded_probability)}</dd></div>}
                    {expense && <div><dt className="text-xs text-[var(--studio-text-muted)]">{tr('取り置き', 'Earmark')}</dt><dd className="font-medium">{event.earmark?.capsule_name ?? (event.withdrawals.length ? tr('計画の作成で作ります', 'Made when the plan is made') : '—')}</dd></div>}
                </dl>
            </Card>
            {expense && <Card>
                <div className="mb-2 flex items-baseline justify-between text-sm"><span className="text-[var(--studio-text-muted)]">{tr('確保額', 'Set aside')}</span>
                    <span><Money value={event.current_funded} currency={currency} className="font-semibold" /><span className="text-xs text-[var(--studio-text-muted)]"> / {formatCurrency(event.target_amount, currency)}</span></span></div>
                <ProgressBar label={tr(`${event.name}の確保`, `${event.name} set aside`)} value={event.current_funded} max={event.target_amount} tone="positive" />
            </Card>}
            {event.withdrawals.length > 0 && <section className="rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <h3 className="mb-2 text-sm font-semibold">{tr('ライフイベントへの取り崩し', 'Drawdowns for the life event')}</h3>
                <ul className="space-y-2 text-sm">{event.withdrawals.map((row, index) => <li key={`${row.account_id}-${row.period}-${index}`}>
                    <p className="flex justify-between gap-2"><span className="truncate">{row.account_name ?? `#${row.account_id}`}</span><Money value={row.amount} currency={currency} className="font-medium" /></p>
                    <p className="text-xs text-[var(--studio-text-muted)]">{scheduleText({ start_period: row.period, interval_months: row.interval_months, repeat_count: row.repeat_count, end_period: row.end_period })}</p>
                </li>)}</ul>
            </section>}
            {event.note && <p className="whitespace-pre-line rounded-2xl bg-[var(--studio-surface)] p-4 text-sm shadow-[var(--mobile-shadow)]">{event.note}</p>}
        </div>
    </Sheet>;
}

/** The goal: what it needs and holds, how net worth may go, and each life event. */
export default function Goals() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const period = clientToday(timezone).slice(0, 7);
    const load = useCallback(async () => {
        const scenarios = await list();
        const goal = scenarios.find((scenario) => scenario.is_goal);
        if (!goal) return null;
        const [comparison, events, check] = await Promise.all([compare([goal.id]), getLifeEventsWithProgress(), planCheck(period)]);
        return { name: goal.name, projected: comparison.scenarios[0], events, check };
    }, [period]);
    const resource = useResource(load);
    const [opened, setOpened] = useState<LifeEventProgress | null>(null);
    const data = resource.data;
    const expenses = data?.events.filter((event) => event.direction === 'expense') ?? [];
    const required = expenses.reduce((total, event) => total + event.target_amount, 0);
    const funded = expenses.reduce((total, event) => total + event.current_funded, 0);
    const outcomes = new Map(data?.projected.events.map((event) => [event.id, event]));
    const figures = data ? [
        [tr('必要額', 'Needed'), formatCurrency(required, currency)], [tr('確保額', 'Set aside'), formatCurrency(funded, currency)],
        [tr('不足', 'Short'), formatCurrency(Math.max(0, required - funded), currency)], [tr('今月の積立', 'Saving this month'), formatCurrency(data.projected.monthly_contribution, currency)],
    ] : [];
    return <Screen title={tr('ゴール', 'Goals')} top>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {resource.loading && !data && <Skeleton lines={3} />}
        {!resource.loading && !resource.error && !data && <Empty icon={<Target size={28} aria-hidden />} title={tr('ゴールのシナリオがありません', 'No goal scenario')} body={tr('PC版のゴールでシナリオを作り、ゴールにしてください。', 'Create a scenario in the desktop goals and make it the goal.')}>
            <a href="/studio/goals/scenarios" className={`mt-1 inline-flex items-center gap-1 text-sm font-medium text-[var(--studio-accent)] ${focusRing}`}>{tr('PC版で開く', 'Open on desktop')}<ExternalLink size={14} aria-hidden /></a>
        </Empty>}
        {data && <>
            <div className="flex items-center justify-between px-1"><p className="text-sm font-semibold">{data.name}</p>
                <a href="/studio/goals" className={`inline-flex items-center gap-1 text-xs font-medium text-[var(--studio-accent)] ${focusRing}`}>{tr('PC版で編集', 'Edit on desktop')}<ExternalLink size={12} aria-hidden /></a></div>
            <div className="grid grid-cols-2 gap-3">{figures.map(([label, value]) => <div key={label} className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]">
                <p className="text-xs text-[var(--studio-text-muted)]">{label}</p><p className="mt-0.5 text-base font-bold tabular-nums">{value}</p>
            </div>)}</div>
            {data.check.goal && <p className="px-1 text-xs text-[var(--studio-text-muted)]">{tr(`今月の計画 ${formatCurrency(data.check.planned, currency)}（積立設定との差 ${data.check.difference >= 0 ? '+' : ''}${formatCurrency(data.check.difference, currency)}）`, `Planned this month ${formatCurrency(data.check.planned, currency)} (${data.check.difference >= 0 ? '+' : ''}${formatCurrency(data.check.difference, currency)} against the contribution settings)`)}</p>}
            <Card>
                <h2 className="mb-1 text-sm font-semibold">{tr('純資産の見通し', 'Net worth outlook')}</h2>
                <p className="mb-2 text-xs text-[var(--studio-text-muted)]">{tr(`${data.projected.horizon_years}年・中央値と P10〜P90 の幅、破線は累計必要額`, `${data.projected.horizon_years} years · the median and the P10–P90 range; the dashed line is the cumulative need`)}</p>
                <ProjectionChart projected={data.projected} currency={currency} />
            </Card>
            <section className="space-y-2">
                <h2 className="px-1 text-xs font-semibold text-[var(--studio-text-muted)]">{tr('ライフイベント', 'Life events')}</h2>
                {data.events.length === 0 && <Empty title={tr('ライフイベントはありません', 'No life events')} body={tr('PC版のゴールで追加できます。', 'Add them in the desktop goals.')} />}
                {data.events.map((event) => {
                    const outcome = outcomes.get(event.id);
                    const expense = event.direction === 'expense';
                    return <button key={event.id} type="button" onClick={() => setOpened(event)}
                        className={`w-full space-y-2 rounded-2xl bg-[var(--studio-surface)] p-4 text-left shadow-[var(--mobile-shadow)] active:bg-[var(--studio-accent-soft)] ${focusRing}`}>
                        <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                                <p className="flex items-center gap-1.5 text-sm font-semibold"><span className="truncate">{event.name}</span>{!expense && <Badge>{KIND_LABELS[event.direction]}</Badge>}</p>
                                <p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--studio-text-muted)]"><CalendarDays size={12} aria-hidden />{formatDate(event.target_date, timezone)}</p>
                            </div>
                            <span className="shrink-0 text-sm font-semibold tabular-nums">{eventAmount(event, currency)}</span>
                        </div>
                        {expense && <ProgressBar label={tr(`${event.name}の確保`, `${event.name} set aside`)} value={event.current_funded} max={event.target_amount} tone="positive" />}
                        <div className="flex flex-wrap gap-1.5">
                            <Badge tone={(outcome?.executed_probability ?? 1) < 0.5 ? 'warning' : 'muted'}>{tr('起きる', 'Happens')} {percent(outcome?.executed_probability)}</Badge>
                            {expense && <Badge tone={(outcome?.funded_probability ?? 1) < 0.5 ? 'danger' : 'accent'}>{tr('足りる', 'Funded')} {percent(outcome?.funded_probability)}</Badge>}
                            {expense && <Badge>{tr(`${event.progress_percentage}% 確保`, `${event.progress_percentage}% set aside`)}</Badge>}
                        </div>
                    </button>;
                })}
            </section>
        </>}
        {opened && <EventSheet event={opened} outcome={outcomes.get(opened.id)} currency={currency} timezone={timezone} onClose={() => setOpened(null)} />}
    </Screen>;
}
