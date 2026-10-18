import { useCallback } from 'react';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { captureBaseline, getBaselineComparison, type BaselineReason, type BaselineRow } from '../../../api/goalBaselines';
import { formatCurrency } from '../../../utils/currency';
import { useConfirm } from '../../components/useConfirm';
import { formatDate } from '../../datetime';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';

const REASONS: Record<BaselineReason, string> = { adopted: 'ゴールに採用したとき', reflection: '予算に反映したとき', manual: '手動で更新' };

function ActualDot(props: { cx?: number; cy?: number; payload?: BaselineRow }) {
    const { cx, cy, payload } = props;
    if (cx === undefined || cy === undefined || !payload || payload.actual === null) return null;
    // Closed months are final; open ones are provisional and drawn hollow.
    return <circle cx={cx} cy={cy} r={4} stroke="var(--studio-text)" strokeWidth={2} fill={payload.closed ? 'var(--studio-text)' : 'var(--studio-surface)'} />;
}

/** The plan chosen at adoption against actual net worth, month by month. */
export default function GoalBaselinePanel({ currency }: { currency: string }) {
    const load = useCallback(() => getBaselineComparison(), []);
    const resource = useResource(load);
    const mutation = useMutation();
    const confirm = useConfirm();
    const data = resource.data;
    const capture = async (replace: boolean) => {
        if (replace && !(await confirm('今のゴールの予測で基準線を作り直しますか？\n以前の基準線は履歴に残り、実績との比較は新しい基準線で行います。', '作り直す'))) return;
        void mutation.run(() => captureBaseline(), '基準線を保存しました。', resource.reload);
    };
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    const rows = (data?.rows ?? []).map((row) => ({ ...row, band: [row.p10, row.p90] }));
    const latest = data?.latest;
    const state = !data ? null : !data.baseline ? '基準線がありません'
        : !latest ? null
            : latest.below_p10 ? '慎重な想定（P10）を下回っています' : latest.difference >= 0 ? '基準を上回っています' : '基準の範囲内です';
    // Closed by default; the state and a shortfall stay visible without opening it.
    return <section className="space-y-2">
        <details className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <summary className="cursor-pointer">
            <h3 className="inline font-semibold">基準線と実績</h3>
            {state && <span className={`ml-3 text-xs ${latest?.below_p10 ? 'text-[var(--studio-warning)]' : 'text-[var(--studio-text-muted)]'}`}>{state}</span>}
        </summary>
        {data?.baseline && <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-[var(--studio-text-muted)]">基準線：{data.baseline.scenario_name}（{formatDate(data.baseline.anchor_date)}、{REASONS[data.baseline.reason]}）／ 月の積立 {formatCurrency(data.baseline.assumptions.monthly_savings, currency)}・年利 {data.baseline.assumptions.annual_return}%</p>
            <button type="button" disabled={mutation.busy} onClick={() => void capture(true)} className={buttonClass}>基準線を作り直す</button>
        </div>}
        <Feedback loading={resource.loading} error={resource.error || mutation.error} message={mutation.message} />
        {data && !data.baseline && <div className="space-y-3">
            <p className="text-sm text-[var(--studio-text-muted)]">基準線がありません。今のゴールの予測を基準線として保存すると、毎月の実際の純資産と比べられます（ゴールを選んだときは自動で保存されます）。</p>
            <button type="button" disabled={mutation.busy} onClick={() => void capture(false)} className={primaryClass}>今の予測を基準線にする</button>
        </div>}
        {data?.baseline && <>
            {latest && <dl className="grid gap-3 sm:grid-cols-3">
                {[
                    [`実績（${latest.period}・${latest.closed ? '確定' : '暫定'}）`, formatCurrency(latest.actual, currency)],
                    ['基準の中央値', formatCurrency(latest.p50, currency)],
                    ['差', `${latest.difference >= 0 ? '+' : ''}${formatCurrency(latest.difference, currency)}`],
                ].map(([label, value], index) => <div key={label} className="rounded-lg border border-[var(--studio-border)] p-3">
                    <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                    <dd className={`mt-1 font-semibold tabular-nums ${index === 2 && latest.difference < 0 ? 'text-[var(--studio-danger)]' : ''}`}>{value}</dd>
                </div>)}
            </dl>}
            <div role="img" aria-label={`基準線と実績の純資産。横軸：月、縦軸：金額（${currency}）。基準のP10〜P90と中央値、月末の実績（塗りつぶしは締め済み、白抜きは暫定）`} className="h-72 min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={rows} margin={{ top: 20, right: 20, bottom: 28, left: 20 }} accessibilityLayer>
                        <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                        <XAxis dataKey="period" tick={axisStyle} minTickGap={30} label={{ value: '月', position: 'bottom', ...axisStyle }} />
                        <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                        <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} formatter={(value, name) => [Array.isArray(value) ? value.map((amount) => formatCurrency(Number(amount), currency)).join('〜') : formatCurrency(Number(value), currency), name]} />
                        <Legend verticalAlign="top" />
                        <Area type="linear" dataKey="band" name="基準 P10〜P90" stroke="none" fill="var(--studio-accent)" fillOpacity={0.12} isAnimationActive={false} />
                        <Line type="linear" dataKey="p50" name="基準の中央値" stroke="var(--studio-accent)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                        <Line type="linear" dataKey="actual" name="実績（月末）" stroke="var(--studio-text)" strokeWidth={2} dot={<ActualDot />} connectNulls={false} isAnimationActive={false} />
                    </ComposedChart>
                </ResponsiveContainer>
            </div>
            <p className="text-xs text-[var(--studio-text-muted)]">実績は有効な口座の月末の純資産です。月次の締めをした月は確定（塗りつぶし）、それ以外は暫定（白抜き）で、今月は今日時点の値です。</p>
        </>}
        </details>
        {latest?.below_p10 && <p role="alert" className="text-sm text-[var(--studio-warning)]">実績が基準線の慎重な想定を下回っています。積立額の見直し、ライフイベントの時期の変更、別シナリオとの比較を検討してください。</p>}
    </section>;
}
