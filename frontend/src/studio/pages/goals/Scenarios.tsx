import { useConfirm } from '../../components/useConfirm';
import { useCallback, useRef, useState } from 'react';
import { applyMilestonesFromSimulation, compareSimulationScenarios, getSimulationScenarios, previewMilestonesFromSimulation } from '../../../api';
import type { ContributionScheduleItem, LifeEvent, MilestoneSimulationBasis, MilestoneSimulationInterval, MilestoneSimulationPreview, MilestoneSimulationRequest, SimulationScenario, SimulationScenarioCompareItem } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

const BASES: Partial<Record<MilestoneSimulationBasis, string>> = { deterministic: '一定利回りの試算', p10: '下位10%（P10）', p50: '中央値（P50）', p90: '上位10%（P90）' };
const INTERVALS: Record<MilestoneSimulationInterval, string> = { annual: '毎年', semiannual: '半年ごと', quarterly: '四半期ごと', target_only: '目標日のみ' };
const percent = (value: number) => new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value);

function Schedule({ items, currency }: { items: ContributionScheduleItem[]; currency: string }) {
    return items.length ? <ul className="space-y-1 text-xs text-[var(--studio-text-muted)]">
        {items.map((item, index) => <li key={index}>
            {item.kind === 'monthly' ? '毎月' : item.kind === 'yearly' ? `毎年${item.month ?? '未設定'}月` : item.date || '日付未設定'}：{formatCurrency(item.amount, currency)}（{currency}）
            {item.kind !== 'one_time' && ` ／ ${item.start_date || '現在'} 〜 ${item.end_date || '目標日'}`}
            {item.note && ` ／ ${item.note}`}
        </li>)}
    </ul> : <p className="text-xs text-[var(--studio-text-muted)]">個別の積立予定なし</p>;
}

function Assumptions({ scenario, currency }: { scenario: SimulationScenario; currency: string }) {
    return <div className="space-y-2">
        <p className="text-xs">年利 {scenario.annual_return}% ／ インフレ {scenario.inflation}% ／ {scenario.allocation_mode === 'direct' ? 'このゴールへ直接配分' : '優先度で配分'}</p>
        <p className="text-xs">月額積立：{scenario.monthly_savings == null ? 'システム設定に従う' : `${formatCurrency(scenario.monthly_savings, currency)}（${currency}）`}</p>
        <Schedule items={scenario.contribution_schedule} currency={currency} />
    </div>;
}

function Comparison({ items, currency }: { items: SimulationScenarioCompareItem[]; currency: string }) {
    const metrics: Array<{ label: string; value: (item: SimulationScenarioCompareItem) => string }> = [
        { label: '目標額', value: (item) => formatCurrency(item.target_amount, currency) },
        { label: '目標までの年数', value: (item) => `${item.years_remaining}年` },
        { label: '達成確率', value: (item) => `${percent(item.probability)}%` },
        { label: '目標日の下位10%（P10）', value: (item) => formatCurrency(item.percentiles.p10, currency) },
        { label: '目標日の中央値（P50）', value: (item) => formatCurrency(item.percentiles.p50, currency) },
        { label: '目標日の上位10%（P90）', value: (item) => formatCurrency(item.percentiles.p90, currency) },
        { label: '目標日の一定利回りの試算', value: (item) => formatCurrency(item.deterministic_yearly.at(-1)?.end_balance, currency) },
    ];
    const years = [...new Set(items.flatMap((item) => item.deterministic_yearly.map((row) => row.year)))].sort((a, b) => a - b);
    return <section className="space-y-3">
        <h4 className="text-sm font-semibold">２案の比較（{currency}）</h4>
        <p className="text-xs text-[var(--studio-text-muted)]">現在の確保額と保存案の前提で再計算した結果です。</p>
        <DataTable columns={['比較項目', ...items.map((item) => item.scenario_name)]}>
            {metrics.map((metric) => <tr key={metric.label}><th scope="row" className="px-5 py-3 font-medium">{metric.label}</th>{items.map((item) => <td key={item.scenario_id} className="whitespace-nowrap px-5 py-3 tabular-nums">{metric.value(item)}</td>)}</tr>)}
        </DataTable>
        <details><summary className="cursor-pointer text-sm text-[var(--studio-text-muted)]">年ごとの推移（一定利回り）</summary>
            <div className="mt-3"><DataTable columns={['現在からの年数', ...items.map((item) => item.scenario_name)]}>
                {years.map((year) => <tr key={year}><th scope="row" className="px-5 py-3 font-normal">{year}年</th>{items.map((item) => {
                    const row = item.deterministic_yearly.find((candidate) => candidate.year === year);
                    return <td key={item.scenario_id} className="whitespace-nowrap px-5 py-3 tabular-nums">{row ? formatCurrency(row.end_balance, currency) : '—'}</td>;
                })}</tr>)}
            </DataTable></div>
        </details>
    </section>;
}

export default function Scenarios({ goal, currency, clientName, onAdopted, onBusy }: {
    goal: LifeEvent; currency: string; clientName?: string;
    onAdopted: () => void; onBusy: (busy: boolean) => void;
}) {
    const confirm = useConfirm();
    const load = useCallback(() => getSimulationScenarios(goal.id), [goal.id]);
    const resource = useResource(load);
    const mutation = useMutation();
    const inFlight = useRef(false);
    const [selected, setSelected] = useState<number[]>([]);
    const [comparison, setComparison] = useState<SimulationScenarioCompareItem[] | null>(null);
    const [basis, setBasis] = useState<MilestoneSimulationBasis>('deterministic');
    const [interval, setInterval] = useState<MilestoneSimulationInterval>('annual');
    const [preview, setPreview] = useState<{ scenario: SimulationScenario; request: MilestoneSimulationRequest; data: MilestoneSimulationPreview } | null>(null);
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || !clientName;
    const run = (action: () => Promise<unknown>, message: string, onSuccess: () => void) => {
        // Keep the parent locked if another click arrives before busy has rendered.
        if (inFlight.current) return;
        inFlight.current = true;
        onBusy(true);
        void mutation.run(action, message, onSuccess).finally(() => { inFlight.current = false; onBusy(false); });
    };
    const compare = () => {
        if (disabled || selected.length !== 2) return;
        setComparison(null);
        let result: SimulationScenarioCompareItem[] = [];
        run(async () => { result = await compareSimulationScenarios(goal.id, [selected[0], selected[1]]); }, '２案を比較しました。', () => setComparison(result));
    };
    const showPreview = (scenario: SimulationScenario) => {
        if (disabled) return;
        setPreview(null);
        // Freeze the exact assumptions reviewed by the user for the later apply call.
        const request: MilestoneSimulationRequest = {
            basis, interval, mode: 'replace', n_simulations: 1000,
            annual_return: scenario.annual_return, inflation: scenario.inflation,
            monthly_savings: scenario.monthly_savings ?? undefined,
            contribution_schedule: scenario.contribution_schedule, allocation_mode: scenario.allocation_mode,
        };
        let data: MilestoneSimulationPreview | null = null;
        run(async () => { data = await previewMilestonesFromSimulation(goal.id, request); }, `「${scenario.name}」の採用前プレビューを取得しました。`, () => {
            if (data) setPreview({ scenario, request, data });
        });
    };
    const adopt = async () => {
        if (disabled || !preview || !preview.data.items.length || preview.data.life_event_id !== goal.id) return;
        if (!(await confirm(`「${clientName}」のゴール「${goal.name}」に「${preview.scenario.name}」を採用します。\n現在のマイルストーン${preview.data.existing_count}件を置き換え、プレビューの前提から${preview.data.items.length}件を再生成します。\n採用したマイルストーンは、システム全体でこのゴールの計画・進捗判定の基準になります。\n採用時に再計算するため、現在の確保額や基準日が変わると金額も変わる場合があります。\nこの計画へ切り替えますか？`, '採用する'))) return;
        run(() => applyMilestonesFromSimulation(goal.id, preview.request), `「${preview.scenario.name}」の前提をゴールの計画として採用しました。`, () => {
            setPreview(null);
            setComparison(null);
            onAdopted();
        });
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-base font-semibold">保存した計画案</h3>
            <button type="button" disabled={resource.loading || mutation.busy} onClick={() => { setPreview(null); setComparison(null); setSelected([]); resource.reload(); }} className={buttonClass}>計画案を再読み込み</button>
        </div>
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        <fieldset disabled={disabled} className="grid gap-4 sm:grid-cols-2">
            <Field label="採用する試算の基準"><select value={basis} onChange={(event) => { setBasis(event.target.value as MilestoneSimulationBasis); setPreview(null); }} className={inputClass}>{Object.entries(BASES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="マイルストーンの間隔"><select value={interval} onChange={(event) => { setInterval(event.target.value as MilestoneSimulationInterval); setPreview(null); }} className={inputClass}>{Object.entries(INTERVALS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        </fieldset>
        {resource.data && <DataTable columns={['比較する', '計画案', '前提・積立予定', '採用前の確認']}>
            {resource.data.length ? resource.data.map((scenario) => <tr key={scenario.id}>
                <td className="px-5 py-3"><input type="checkbox" checked={selected.includes(scenario.id)} disabled={disabled || (selected.length === 2 && !selected.includes(scenario.id))} aria-label={`${scenario.name}を比較対象にする`} onChange={(event) => { setSelected((previous) => event.target.checked ? [...previous, scenario.id] : previous.filter((id) => id !== scenario.id)); setComparison(null); }} /></td>
                <th scope="row" className="px-5 py-3 font-medium">{scenario.name}{scenario.description && <p className="mt-1 text-xs font-normal text-[var(--studio-text-muted)]">{scenario.description}</p>}</th>
                <td className="min-w-64 px-5 py-3"><Assumptions scenario={scenario} currency={currency} /></td>
                <td className="px-5 py-3"><button type="button" disabled={disabled} onClick={() => showPreview(scenario)} aria-label={`${scenario.name}の採用前プレビュー`} className={buttonClass}>採用前プレビュー</button></td>
            </tr>) : <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">このゴールの保存案はありません。</td></tr>}
        </DataTable>}
        <div className="flex items-center gap-3"><button type="button" disabled={disabled || selected.length !== 2} onClick={compare} className={buttonClass}>２案を比較</button><span className="text-xs text-[var(--studio-text-muted)]">選択：{selected.length} / 2案</span></div>
        {comparison && <Comparison items={comparison} currency={currency} />}
        {preview && <section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <h4 className="text-sm font-semibold">「{preview.scenario.name}」の採用前プレビュー</h4>
            <Assumptions scenario={preview.scenario} currency={currency} />
            <p className="text-xs text-[var(--studio-text-muted)]">{BASES[preview.request.basis]} ／ {INTERVALS[preview.request.interval]} ／ 既存{preview.data.existing_count}件を置き換え、{preview.data.items.length}件を採用します。</p>
            <p className="text-xs text-[var(--studio-text-muted)]">採用時に同じ前提で再計算します。現在の確保額や基準日が変わると、金額はこのプレビューと異なる場合があります。</p>
            <DataTable columns={['予定日', '計画額']}>
                {preview.data.items.length ? preview.data.items.map((item, index) => <tr key={`${item.date}:${index}`}><th scope="row" className="whitespace-nowrap px-5 py-3 font-normal">{item.date}</th><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(item.target_amount, currency)}</td></tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">採用できるマイルストーンはありません。</td></tr>}
            </DataTable>
            <p className="text-sm">採用すると、システム全体のゴール計画・進捗判定の基準がこのマイルストーンに切り替わります。</p>
            <div className="flex gap-2"><button type="button" disabled={disabled || !preview.data.items.length} onClick={adopt} className={primaryClass}>この案を計画として採用</button><button type="button" disabled={mutation.busy} onClick={() => setPreview(null)} className={buttonClass}>プレビューを閉じる</button></div>
        </section>}
    </section>;
}
