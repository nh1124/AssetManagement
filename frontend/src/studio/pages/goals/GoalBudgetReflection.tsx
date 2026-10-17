import { useEffect, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import { getAccounts } from '../../../api';
import { applyGoalBudget, previewGoalBudget, type GoalBudgetEvent, type GoalBudgetOptions, type GoalBudgetPreview, type GoalBudgetResult } from '../../../api/goalBudget';
import { useClient } from '../../../context/ClientContext';
import type { Account } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { assetErrorMessage } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { inputClass, primaryClass } from '../db/forms';
import { REFLECTIONS } from './presentation';

const NEAR_YEARS = [1, 3, 5, 10];
const MONTHS = [1, 3, 6, 12];

function treatment(row: GoalBudgetEvent): string {
    switch (row.status) {
        case 'reflected': return row.near ? (row.create_capsule ? '取り置きを作成して積立' : '取り置きで積立') : '毎月の積立に含む';
        case 'condition_unmet': return `見込み（前提条件 ${row.conditions_met}/${row.conditions_total}件を満たす）`;
        case 'condition_unknown': return '見込み（判定できない前提条件あり）';
        case 'simulation_only': return '反映しない';
        case 'income': return '収入見込み（予算には載せない）';
        case 'past_due': return '目標日を過ぎています';
        case 'no_capsule': return '取り置きが無いため反映しない';
    }
}

/** Reflect the goal into the budget: choose, see every row that would change, then confirm. */
export default function GoalBudgetReflection({ title = 'ゴールを予算に反映', intro, initialPeriod, onClose, onApplied }: {
    title?: string; intro?: string; initialPeriod?: string;
    onClose: () => void; onApplied?: (result: GoalBudgetResult) => void;
}) {
    const timezone = useTimezone();
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [options, setOptions] = useState<GoalBudgetOptions>(() => ({
        savings_source: 'scenario', near_years: 5, start_period: initialPeriod ?? clientToday(timezone).slice(0, 7),
        months: 1, savings_account_id: null, create_capsules: [],
    }));
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [preview, setPreview] = useState<GoalBudgetPreview | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [refresh, setRefresh] = useState(0);
    // Suggestions fill the first preview only; afterwards every choice is the user's.
    const defaulted = useRef(false);
    const revision = useRef(0);

    useEffect(() => {
        let live = true;
        void getAccounts('asset', true).then((rows) => { if (live) setAccounts(rows.filter((row) => row.is_active)); }).catch(() => {});
        return () => { live = false; };
    }, []);

    useEffect(() => {
        const request = ++revision.current;
        setLoading(true);
        const timer = window.setTimeout(() => {
            void previewGoalBudget(options).then((result) => {
                if (request !== revision.current) return;
                if (!defaulted.current) {
                    defaulted.current = true;
                    const missing = result.events.filter((row) => row.status === 'no_capsule').map((row) => row.event_id);
                    const account = result.savings.suggested_account_id;
                    if (missing.length || account !== null) {
                        // Creating capsules is the default answer, as when choosing a goal.
                        setOptions((previous) => ({ ...previous, create_capsules: missing, savings_account_id: previous.savings_account_id ?? account }));
                        return;
                    }
                }
                setPreview(result);
                setError('');
                setLoading(false);
            }).catch((failure: unknown) => {
                if (request !== revision.current) return;
                setPreview(null);
                setError(assetErrorMessage(failure));
                setLoading(false);
            });
        }, 250);
        return () => window.clearTimeout(timer);
    }, [options, refresh]);

    const choose = <K extends keyof GoalBudgetOptions>(key: K, value: GoalBudgetOptions[K]) => {
        setMessage('');
        setOptions((previous) => ({ ...previous, [key]: value }));
    };
    const toggleCapsule = (eventId: number, checked: boolean) => choose('create_capsules', checked
        ? [...options.create_capsules, eventId] : options.create_capsules.filter((id) => id !== eventId));
    const changed = preview?.changes.filter((row) => row.changed) ?? [];
    const accountName = (id: number | null) => (id === null ? '—' : accounts.find((row) => row.id === id)?.name ?? `口座 ${id}`);
    const apply = async () => {
        if (!preview || busy || loading || !changed.length) return;
        setBusy(true);
        setError('');
        try {
            const result = await applyGoalBudget(options, preview.fingerprint);
            const created = result.created_capsules.length ? `取り置きを${result.created_capsules.length}件作成しました。` : '';
            setMessage(`予算に${result.applied}件反映しました。${created}`);
            setRefresh((value) => value + 1);
            onApplied?.(result);
        } catch (failure: unknown) {
            setError(assetErrorMessage(failure));
            // A conflict means the preview is stale; show the current one before another attempt.
            if (isAxiosError(failure) && failure.response?.status === 409) setRefresh((value) => value + 1);
        } finally {
            setBusy(false);
        }
    };
    const savings = preview?.savings;
    return <Overlay title={title} onClose={() => { if (!busy) onClose(); }}
        footer={<button type="button" disabled={busy || loading || !preview || !changed.length} onClick={() => void apply()} className={primaryClass}>{busy ? '反映中…' : '予算に反映する'}</button>}>
        <div className="space-y-6">
            {intro && <p className="text-sm">{intro}</p>}
            <section className="space-y-3">
                <h3 className="text-sm font-semibold">反映のしかた</h3>
                <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
                    <fieldset className="space-y-2 sm:col-span-2">
                        <legend className="text-sm text-[var(--studio-text-muted)]">毎月の積立額</legend>
                        {(['scenario', 'required'] as const).map((value) => <label key={value} className="flex items-center gap-2 text-sm">
                            <input type="radio" name="savings_source" checked={options.savings_source === value} onChange={() => choose('savings_source', value)} />
                            {value === 'scenario' ? 'シナリオの月の積立' : 'ライフイベントに必要な額'}
                            {savings && <span className="tabular-nums text-[var(--studio-text-muted)]">{formatCurrency(value === 'scenario' ? savings.scenario_amount : savings.required_amount, currency)}</span>}
                        </label>)}
                    </fieldset>
                    <Field label="取り置きで積み立てる範囲"><select value={options.near_years} onChange={(event) => choose('near_years', Number(event.target.value))} className={inputClass}>
                        {NEAR_YEARS.map((years) => <option key={years} value={years}>{years}年以内のライフイベント</option>)}
                    </select></Field>
                    <Field label="積立先の口座"><select value={options.savings_account_id ?? ''} onChange={(event) => choose('savings_account_id', event.target.value ? Number(event.target.value) : null)} className={inputClass}>
                        <option value="">選ばない（取り置きだけ反映）</option>
                        {accounts.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
                    </select></Field>
                    <Field label="反映する最初の月"><input type="month" required value={options.start_period} onChange={(event) => { if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value)) choose('start_period', event.target.value); }} className={inputClass} /></Field>
                    <Field label="反映する期間"><select value={options.months} onChange={(event) => choose('months', Number(event.target.value))} className={inputClass}>
                        {MONTHS.map((months) => <option key={months} value={months}>{months}か月</option>)}
                    </select></Field>
                </fieldset>
            </section>
            <Feedback loading={loading} error={error} message={message} />
            {preview && savings && <>
                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">毎月の積立（{preview.scenario.name}）</h3>
                    <p className="text-sm tabular-nums">{formatCurrency(savings.chosen_amount, currency)} ＝ 取り置き {formatCurrency(savings.capsule_amount, currency)} ＋ 積立先 {formatCurrency(savings.account_amount, currency)}</p>
                    {savings.shortfall > 0 && <p role="alert" className="text-sm text-[var(--studio-warning)]">近いライフイベントの取り置きだけで、毎月の積立額を {formatCurrency(savings.shortfall, currency)} 超えています。</p>}
                    {savings.account_required && <p className="text-xs text-[var(--studio-text-muted)]">積立先の口座を選ぶと、残りの {formatCurrency(savings.account_amount, currency)} も予算に入ります。</p>}
                    <p className="text-xs text-[var(--studio-text-muted)]">遠いライフイベントの必要額は、税引後の年利 {preview.scenario.after_tax_return.toFixed(1)}% で運用する前提で計算しています。</p>
                </section>
                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">ライフイベントの扱い</h3>
                    <DataTable columns={['ライフイベント', '目標日', '予算への反映', '扱い', '月額', '取り置きを作る']}>
                        {preview.events.map((row) => {
                            const creatable = row.status === 'no_capsule' || Boolean(row.create_capsule);
                            return <tr key={`event-${row.event_id}`}>
                                <th scope="row" className="px-5 py-3 font-medium">{row.name}</th>
                                <td className="whitespace-nowrap px-5 py-3">{formatDate(row.target_date)}</td>
                                <td className="whitespace-nowrap px-5 py-3">{row.direction === 'income' ? '—' : REFLECTIONS[row.reflection]}</td>
                                <td className="px-5 py-3">{treatment(row)}</td>
                                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.status === 'reflected' || row.status === 'no_capsule' ? formatCurrency(row.monthly_required, currency) : '—'}</td>
                                <td className="px-5 py-3">{creatable ? <input type="checkbox" aria-label={`${row.name}の取り置きを作成する`} disabled={busy} checked={options.create_capsules.includes(row.event_id)} onChange={(event) => toggleCapsule(row.event_id, event.target.checked)} /> : '—'}</td>
                            </tr>;
                        })}
                        {preview.events.length === 0 && <tr><td colSpan={6} className="px-5 py-3 text-[var(--studio-text-muted)]">ゴールにライフイベントがありません。</td></tr>}
                    </DataTable>
                    <p className="text-xs text-[var(--studio-text-muted)]">予算への反映（確定・条件つき・試算のみ）は、各ライフイベントの編集で変えられます。</p>
                </section>
                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">予算の変更</h3>
                    {changed.length ? <DataTable columns={['月', '項目', '口座', '現在', '反映後']}>
                        {changed.map((row, index) => <tr key={`change-${row.period}-${row.kind}-${row.line_id ?? index}`}>
                            <td className="whitespace-nowrap px-5 py-3">{row.period}</td>
                            <th scope="row" className="px-5 py-3 font-medium">{row.kind === 'retire' ? `${row.name}（以前の反映を取り消す）` : row.kind === 'savings' ? '積立' : `取り置き：${row.name}`}</th>
                            <td className="px-5 py-3">{row.kind === 'capsule' && row.account_id === null ? '口座の指定なし' : accountName(row.account_id)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.current_amount === null ? '未設定' : formatCurrency(row.current_amount, currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.kind === 'retire' ? '削除' : formatCurrency(row.new_amount, currency)}</td>
                        </tr>)}
                    </DataTable> : <p className="text-sm text-[var(--studio-text-muted)]">予算は今の内容のままで、変更はありません。</p>}
                </section>
            </>}
        </div>
    </Overlay>;
}
