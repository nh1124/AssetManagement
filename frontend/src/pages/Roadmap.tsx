import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CalendarDays, Flag, RefreshCw, TrendingUp } from 'lucide-react';
import {
    Area,
    ComposedChart,
    Legend,
    Line,
    ReferenceLine,
    ResponsiveContainer,
    Scatter,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import { getRoadmapProjection } from '../api';
import type { RoadmapProjection } from '../types';

const formatCurrency = (value: number | undefined | null) => `JPY ${Math.round(value || 0).toLocaleString()}`;
const compactCurrency = (value: number | undefined | null) => {
    const raw = Math.round(value || 0);
    if (Math.abs(raw) >= 100000000) return `JPY ${(raw / 100000000).toFixed(1)}oku`;
    if (Math.abs(raw) >= 10000) return `JPY ${(raw / 10000).toFixed(0)}man`;
    return `JPY ${raw.toLocaleString()}`;
};

type RoadmapParams = {
    years: number;
    annual_return: number;
    inflation: number;
    monthly_savings: number;
};

type ChartPoint = {
    label: string;
    sort: number;
    actual?: number;
    p10?: number;
    p50?: number;
    p90?: number;
    band?: number;
    liability?: number;
    milestone?: number;
    milestone_notes?: string[];
    risk?: boolean;
};

const statusTone = (status?: string) => {
    if (status === 'On Track') return 'text-emerald-300 border-emerald-800 bg-emerald-950/30';
    if (status === 'At Risk') return 'text-amber-300 border-amber-800 bg-amber-950/30';
    return 'text-rose-300 border-rose-800 bg-rose-950/30';
};

const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    const rows = payload.filter((item: any) => item.value !== undefined && item.value !== null);
    const point = rows[0]?.payload as ChartPoint | undefined;

    return (
        <div className="bg-slate-950 border border-slate-700 p-3 text-xs shadow-xl min-w-52">
            <p className="text-slate-300 mb-2 font-mono-nums">{label}</p>
            <div className="space-y-1">
                {rows.map((item: any) => {
                    if (item.dataKey === 'band' || item.dataKey === 'p10') return null;
                    return (
                        <div key={item.dataKey} className="flex justify-between gap-4">
                            <span style={{ color: item.color }}>{item.name}</span>
                            <span className="font-mono-nums text-slate-100">{formatCurrency(item.value)}</span>
                        </div>
                    );
                })}
            </div>
            {point?.milestone_notes?.length ? (
                <div className="mt-2 border-t border-slate-800 pt-2 text-slate-400">
                    {point.milestone_notes.map((note) => <p key={note}>{note}</p>)}
                </div>
            ) : null}
        </div>
    );
};

export default function Roadmap() {
    const [data, setData] = useState<RoadmapProjection | null>(null);
    const [loading, setLoading] = useState(false);
    const [params, setParams] = useState<RoadmapParams>({
        years: 30,
        annual_return: 5,
        inflation: 2,
        monthly_savings: 50000,
    });

    const loadProjection = async () => {
        setLoading(true);
        try {
            setData(await getRoadmapProjection(params));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadProjection();
    }, []);

    useEffect(() => {
        const timer = window.setTimeout(loadProjection, 300);
        return () => window.clearTimeout(timer);
    }, [params.years, params.annual_return, params.inflation, params.monthly_savings]);

    const chartData = useMemo<ChartPoint[]>(() => {
        if (!data) return [];
        const demandByYear = new Map(data.liability_demand.map((row) => [row.year, row.cumulative_target]));
        const milestonesByYear = new Map<number, { total: number; notes: string[] }>();
        data.milestones.forEach((milestone) => {
            const year = Number(milestone.date.slice(0, 4));
            const current = milestonesByYear.get(year) ?? { total: 0, notes: [] };
            current.total += milestone.target_amount || 0;
            current.notes.push(`${milestone.date} ${milestone.life_event_name || 'Milestone'}: ${compactCurrency(milestone.target_amount)}`);
            milestonesByYear.set(year, current);
        });

        const history = data.history.map((row) => {
            const [year, month] = row.period.split('-').map(Number);
            return {
                label: row.period,
                sort: year + (month - 1) / 12,
                actual: row.net_worth,
            };
        });

        const projection = data.projection.map((row) => {
            const milestone = milestonesByYear.get(row.year);
            const liability = demandByYear.get(row.year) ?? 0;
            return {
                label: String(row.year),
                sort: row.year,
                p10: row.p10,
                p50: row.p50,
                p90: row.p90,
                band: Math.max(0, row.p90 - row.p10),
                liability,
                milestone: milestone?.total,
                milestone_notes: milestone?.notes,
                risk: row.p50 < liability,
            };
        });

        return [...history, ...projection].sort((a, b) => a.sort - b.sort);
    }, [data]);

    const firstRisk = useMemo(() => chartData.find((row) => row.risk), [chartData]);
    const totals = useMemo(() => {
        const goals = data?.events ?? [];
        return {
            target: goals.reduce((sum, goal) => sum + (goal.target_amount || 0), 0),
            projected: goals.reduce((sum, goal) => sum + (goal.projected_amount || 0), 0),
            count: goals.length,
            milestones: data?.milestones.length ?? 0,
        };
    }, [data]);

    return (
        <div className="h-full overflow-auto p-4 space-y-4">
            <div className="flex flex-col min-[760px]:flex-row min-[760px]:items-center justify-between gap-3">
                <div>
                    <h1 className="text-xl font-semibold text-slate-100">Roadmap</h1>
                </div>
                <button
                    onClick={loadProjection}
                    disabled={loading}
                    className="self-start min-[760px]:self-auto bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 text-xs text-slate-300 flex items-center gap-2 disabled:opacity-50"
                >
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
                </button>
            </div>

            <div className="grid grid-cols-2 min-[980px]:grid-cols-4 gap-3">
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Progression</p>
                    <p className={`mt-1 inline-flex px-2 py-1 border text-xs font-medium ${statusTone(data?.roadmap_progression)}`}>
                        {data?.roadmap_progression ?? 'Loading'} / {Math.round(data?.roadmap_progression_pct ?? 0)}%
                    </p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Future Demand</p>
                    <p className="text-lg text-rose-300 font-mono-nums">{compactCurrency(totals.target)}</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Projected Goals</p>
                    <p className="text-lg text-emerald-300 font-mono-nums">{compactCurrency(totals.projected)}</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Goals / Milestones</p>
                    <p className="text-lg text-slate-100 font-mono-nums">{totals.count} / {totals.milestones}</p>
                </div>
            </div>

            <div className="grid grid-cols-1 min-[1180px]:grid-cols-[1fr_360px] gap-4">
                <section className="bg-slate-900/60 border border-slate-800 min-h-[620px] p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                        <div className="flex items-center gap-2 text-xs text-slate-400 uppercase tracking-wider">
                            <TrendingUp size={14} className="text-emerald-400" /> Net Worth vs Future Liability
                        </div>
                        {firstRisk && (
                            <div className="flex items-center gap-2 text-xs text-rose-300">
                                <AlertTriangle size={14} /> Risk starts {firstRisk.label}
                            </div>
                        )}
                    </div>

                    <div className="h-[540px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <ComposedChart data={chartData} margin={{ top: 18, right: 24, bottom: 18, left: 14 }}>
                                <XAxis
                                    dataKey="label"
                                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                                    interval="preserveStartEnd"
                                    minTickGap={24}
                                />
                                <YAxis
                                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                                    tickFormatter={(value) => compactCurrency(Number(value)).replace('JPY ', '')}
                                    width={72}
                                />
                                <Tooltip content={<CustomTooltip />} />
                                <Legend wrapperStyle={{ fontSize: 12 }} />
                                <Area dataKey="p10" stackId="projection-band" stroke="none" fill="transparent" name="P10" />
                                <Area dataKey="band" stackId="projection-band" stroke="none" fill="#22c55e" fillOpacity={0.12} name="P10-P90" />
                                <Line type="monotone" dataKey="actual" stroke="#34d399" strokeWidth={2.4} dot={false} name="Actual Net Worth" connectNulls={false} />
                                <Line type="monotone" dataKey="p50" stroke="#22c55e" strokeWidth={2.2} strokeDasharray="6 4" dot={false} name="Projected P50" connectNulls={false} />
                                <Line type="monotone" dataKey="liability" stroke="#fb7185" strokeWidth={2} dot={false} name="Liability Demand" connectNulls={false} />
                                <Scatter dataKey="milestone" fill="#38bdf8" name="Milestones" />
                                {firstRisk && <ReferenceLine x={firstRisk.label} stroke="#fb7185" strokeDasharray="4 4" />}
                            </ComposedChart>
                        </ResponsiveContainer>
                    </div>
                </section>

                <aside className="space-y-4">
                    <section className="bg-slate-900/60 border border-slate-800 p-4">
                        <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-4">Parameters</h2>
                        <div className="space-y-4">
                            <label className="block">
                                <div className="flex justify-between text-xs mb-2">
                                    <span className="text-slate-400">Annual Return</span>
                                    <span className="font-mono-nums text-emerald-300">{params.annual_return.toFixed(1)}%</span>
                                </div>
                                <input type="range" min="-5" max="12" step="0.5" value={params.annual_return} onChange={(event) => setParams({ ...params, annual_return: Number(event.target.value) })} className="w-full" />
                            </label>
                            <label className="block">
                                <div className="flex justify-between text-xs mb-2">
                                    <span className="text-slate-400">Inflation</span>
                                    <span className="font-mono-nums text-amber-300">{params.inflation.toFixed(1)}%</span>
                                </div>
                                <input type="range" min="0" max="8" step="0.5" value={params.inflation} onChange={(event) => setParams({ ...params, inflation: Number(event.target.value) })} className="w-full" />
                            </label>
                            <label className="block">
                                <div className="flex justify-between text-xs mb-2">
                                    <span className="text-slate-400">Monthly Savings</span>
                                    <span className="font-mono-nums text-cyan-300">{compactCurrency(params.monthly_savings)}</span>
                                </div>
                                <input type="range" min="0" max="300000" step="10000" value={params.monthly_savings} onChange={(event) => setParams({ ...params, monthly_savings: Number(event.target.value) })} className="w-full" />
                            </label>
                            <div className="grid grid-cols-4 gap-2">
                                {[10, 20, 30, 40].map((years) => (
                                    <button
                                        key={years}
                                        onClick={() => setParams({ ...params, years })}
                                        className={`border px-2 py-1.5 text-xs font-mono-nums ${params.years === years ? 'border-cyan-700 bg-cyan-950/40 text-cyan-300' : 'border-slate-700 bg-slate-800/50 text-slate-400 hover:text-slate-200'}`}
                                    >
                                        {years}Y
                                    </button>
                                ))}
                            </div>
                        </div>
                    </section>

                    <section className={`border p-4 ${firstRisk ? 'border-rose-800 bg-rose-950/20' : 'border-emerald-800 bg-emerald-950/20'}`}>
                        <h2 className="text-xs text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
                            <AlertTriangle size={14} className={firstRisk ? 'text-rose-300' : 'text-emerald-300'} /> Recovery Suggestions
                        </h2>
                        {firstRisk ? (
                            <div className="space-y-2 text-xs text-slate-300">
                                <p>P50 falls below demand in <span className="font-mono-nums text-rose-300">{firstRisk.label}</span>.</p>
                                <p>Raise monthly savings by 10-20%, defer lower-priority targets, or move assets into goal allocations with suitable expected return.</p>
                            </div>
                        ) : (
                            <p className="text-xs text-emerald-200">Projected P50 stays above the cumulative liability curve.</p>
                        )}
                    </section>

                    <section className="bg-slate-900/60 border border-slate-800">
                        <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
                            <Flag size={14} className="text-cyan-300" />
                            <h2 className="text-xs text-slate-400 uppercase tracking-wider">Goals</h2>
                        </div>
                        <div className="max-h-[360px] overflow-auto p-3 space-y-2">
                            {(data?.events ?? []).length === 0 ? (
                                <p className="text-xs text-slate-600 py-6 text-center">No goals yet.</p>
                            ) : data?.events.map((goal) => (
                                <div key={goal.id} className="border border-slate-800 bg-slate-800/30 p-3">
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <p className="text-sm text-slate-100 truncate">{goal.name}</p>
                                            <p className="text-[10px] text-slate-500 flex items-center gap-1 mt-1">
                                                <CalendarDays size={11} /> {goal.target_date}
                                            </p>
                                        </div>
                                        <span className={`text-[10px] border px-1.5 py-0.5 ${statusTone(goal.status)}`}>{goal.status ?? 'Off Track'}</span>
                                    </div>
                                    <div className="mt-3 flex items-center gap-3">
                                        <div className="flex-1 h-1.5 bg-slate-950 border border-slate-800 overflow-hidden">
                                            <div className="h-full bg-cyan-500" style={{ width: `${Math.min(goal.progress_percentage || 0, 100)}%` }} />
                                        </div>
                                        <span className="text-[10px] font-mono-nums text-slate-300">{Math.round(goal.progress_percentage || 0)}%</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>
                </aside>
            </div>
        </div>
    );
}
