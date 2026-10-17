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
import { useNotifications } from '../../notificationContext';
import GoalHandovers from './GoalHandovers';
import { REFLECTIONS } from './presentation';

const NEAR_YEARS = [1, 3, 5, 10];
const EXISTING_KINDS = { definition: '定義', manual: '手入力', capsule: '取り置き' };
const sectionClass = 'space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-bg)] p-4';

function Heading({ step, title, note }: { step: number; title: string; note?: string }) {
    return <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-[var(--studio-border)] pb-2">
        <span aria-hidden="true" className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[var(--studio-accent-soft)] text-xs font-semibold text-[var(--studio-accent)]">{step}</span>
        <h3 className="font-semibold">{title}</h3>
        {note && <span className="text-xs text-[var(--studio-text-muted)]">{note}</span>}
    </div>;
}
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
    const notifications = useNotifications();
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [options, setOptions] = useState<GoalBudgetOptions>(() => ({
        savings_source: 'scenario', near_years: 5, start_period: initialPeriod ?? clientToday(timezone).slice(0, 7),
        months: 1, savings_account_id: null, savings_definition_id: null, uncounted: [], create_capsules: [], handovers: [],
    }));
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [preview, setPreview] = useState<GoalBudgetPreview | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [refresh, setRefresh] = useState(0);
    // Q4: the baseline stays as adopted unless the user moves it here.
    const [updateBaseline, setUpdateBaseline] = useState(false);
    // Suggestions fill the first preview only; afterwards every choice is the user's.
    const defaulted = useRef(false);
    // Handover suggestions are taken once, after capsule defaults settle; then they are the user's.
    const handoversDefaulted = useRef(false);
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
                if (!handoversDefaulted.current) {
                    handoversDefaulted.current = true;
                    const picks = result.handover_suggestions.filter((row) => row.suggested > 0 && row.account_id !== null)
                        .map((row) => ({ event_id: row.event_id, account_id: row.account_id as number, amount: row.suggested }));
                    if (picks.length) {
                        setOptions((previous) => ({ ...previous, handovers: picks }));
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
    const toggleCounted = (key: string, counted: boolean) => choose('uncounted', counted
        ? options.uncounted.filter((value) => value !== key) : [...options.uncounted, key]);
    // One destination: an account gets a goal row, a definition has its monthly amount rewritten.
    const destination = options.savings_definition_id !== null ? `d:${options.savings_definition_id}` : options.savings_account_id !== null ? `a:${options.savings_account_id}` : '';
    const chooseDestination = (value: string) => {
        setMessage('');
        const id = value ? Number(value.slice(2)) : null;
        setOptions((previous) => ({ ...previous, savings_account_id: value.startsWith('a:') ? id : null, savings_definition_id: value.startsWith('d:') ? id : null }));
    };
    const definitions = preview?.existing.filter((row) => row.kind === 'definition' && row.updatable) ?? [];
    const changed = preview?.changes.filter((row) => row.changed) ?? [];
    const accountName = (id: number | null) => (id === null ? '—' : accounts.find((row) => row.id === id)?.name ?? `口座 ${id}`);
    const apply = async () => {
        if (!preview || busy || loading) return;
        setBusy(true);
        setError('');
        try {
            const result = await applyGoalBudget(options, preview.fingerprint, updateBaseline);
            const created = result.created_capsules.length ? `取り置きを${result.created_capsules.length}件作成しました。` : '';
            const handed = result.handovers ? `取り置きへの引き継ぎを${result.handovers}件確保しました。` : '';
            setMessage(`予算に${result.applied}件反映しました。${created}${handed}${result.baseline_updated ? '基準線も更新しました。' : ''}`);
            setUpdateBaseline(false);
            // Handed-over amounts are now claimed; the next preview must not offer them again.
            setOptions((previous) => ({ ...previous, handovers: [] }));
            setRefresh((value) => value + 1);
            notifications.refresh();
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
        footer={<button type="button" disabled={busy || loading || !preview} onClick={() => void apply()} className={primaryClass}>{busy ? '反映中…' : changed.length ? '予算に反映する' : '反映を記録する'}</button>}>
        <div className="space-y-5">
            {intro && <p className="text-sm">{intro}</p>}
            <section className={sectionClass}>
                <Heading step={1} title="反映のしかた" note="選ぶと下の内容がすぐ変わります" />
                <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
                    <fieldset className="space-y-2 sm:col-span-2">
                        <legend className="text-sm text-[var(--studio-text-muted)]">毎月の積立額</legend>
                        {(['scenario', 'required'] as const).map((value) => <label key={value} className="flex items-center gap-2 text-sm">
                            <input type="radio" name="savings_source" checked={options.savings_source === value} onChange={() => choose('savings_source', value)} />
                            {value === 'scenario' ? 'シナリオの月の積立' : 'ライフイベントに必要な額'}
                            {savings && <span className="tabular-nums text-[var(--studio-text-muted)]">{formatCurrency(value === 'scenario' ? savings.scenario_amount : savings.required_amount, currency)}</span>}
                        </label>)}
                    </fieldset>
                    <Field label="取り置きで積み立てる範囲"><select value={options.near_years ?? 'all'} onChange={(event) => choose('near_years', event.target.value === 'all' ? null : Number(event.target.value))} className={inputClass}>
                        {NEAR_YEARS.map((years) => <option key={years} value={years}>{years}年以内のライフイベント</option>)}
                        <option value="all">すべてのライフイベント</option>
                    </select></Field>
                    <Field label="残りの積立先"><select value={destination} onChange={(event) => chooseDestination(event.target.value)} className={inputClass}>
                        <option value="">選ばない（取り置きだけ反映）</option>
                        <optgroup label="口座（ゴールの積立として予算に入れる）">
                            {accounts.map((row) => <option key={`a-${row.id}`} value={`a:${row.id}`}>{row.name}</option>)}
                        </optgroup>
                        {definitions.length > 0 && <optgroup label="定義（毎月の金額を書き換える）">
                            {definitions.map((row) => <option key={`d-${row.id}`} value={`d:${row.id}`}>{row.name}</option>)}
                        </optgroup>}
                    </select></Field>
                    <Field label="反映する最初の月"><input type="month" required value={options.start_period} onChange={(event) => { if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value)) choose('start_period', event.target.value); }} className={inputClass} /></Field>
                    <Field label="反映する期間"><select value={options.months} onChange={(event) => choose('months', Number(event.target.value))} className={inputClass}>
                        {MONTHS.map((months) => <option key={months} value={months}>{months}か月</option>)}
                    </select></Field>
                </fieldset>
            </section>
            <Feedback loading={loading} error={error} message={message} />
            {preview && savings && <>
                <section className={sectionClass}>
                    <Heading step={2} title="毎月の積立" note={`ゴール：${preview.scenario.name}`} />
                    <p className="text-sm tabular-nums">{formatCurrency(savings.chosen_amount, currency)} ＝ 予算にある積立 {formatCurrency(savings.existing_amount, currency)}{savings.product_amount > 0 && <> ＋ 消耗品・固定資産 {formatCurrency(savings.product_amount, currency)}</>} ＋ 取り置き {formatCurrency(savings.capsule_amount, currency)} ＋ 残りの積立先 {formatCurrency(savings.account_amount, currency)}</p>
                    {savings.shortfall > 0 && <p role="alert" className="text-sm text-[var(--studio-warning)]">予算にある積立と近いライフイベントの取り置きだけで、毎月の積立額を {formatCurrency(savings.shortfall, currency)} 超えています。</p>}
                    {savings.account_required && <p className="text-xs text-[var(--studio-text-muted)]">残りの積立先を選ぶと、残りの {formatCurrency(savings.account_amount, currency)} も予算に入ります。</p>}
                    {preview.existing.length > 0 && <>
                        <p className="text-xs text-[var(--studio-text-muted)]">予算に既にある積立は、毎月の積立額の一部として先に差し引きます（同じお金を二重に計画しないため）。積立ではない移動は外してください。</p>
                        <DataTable columns={['積立に数える', '種類', '名称', '口座', `月額（${preview.periods[0]}）`]}>
                            {preview.existing.map((row) => <tr key={row.key}>
                                <td className="px-5 py-3">{row.destination ? <span className="text-xs text-[var(--studio-accent)]">残りの積立先</span> : <input type="checkbox" aria-label={`${row.name}を積立に数える`} disabled={busy} checked={row.counted} onChange={(event) => toggleCounted(row.key, event.target.checked)} />}</td>
                                <td className="whitespace-nowrap px-5 py-3">{EXISTING_KINDS[row.kind]}</td>
                                <th scope="row" className="px-5 py-3 font-medium">{row.name || '名称未設定'}</th>
                                <td className="px-5 py-3">{row.kind === 'capsule' ? '—' : accountName(row.account_id)}</td>
                                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.amount, currency)}</td>
                            </tr>)}
                        </DataTable>
                    </>}
                    {preview.products.length > 0 && <>
                        <p className="text-xs text-[var(--studio-text-muted)]">消耗品・固定資産の取り置きには、紐づく物品の推奨月額を毎月入れます（物品ごとの積立先は消耗品・固定資産の画面で設定します）。</p>
                        <DataTable columns={['取り置き', '物品', `月額（${preview.periods[0]}）`]}>
                            {preview.products.map((row) => <tr key={`product-${row.capsule_id}`}>
                                <th scope="row" className="px-5 py-3 font-medium">{row.name}</th>
                                <td className="px-5 py-3">{row.products}件</td>
                                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.monthly, currency)}</td>
                            </tr>)}
                        </DataTable>
                    </>}
                    <p className="text-xs text-[var(--studio-text-muted)]">遠いライフイベントの必要額は、税引後の年利 {preview.scenario.after_tax_return.toFixed(1)}% で運用する前提で計算しています。</p>
                </section>
                <section className={sectionClass}>
                    <Heading step={3} title="ライフイベントの扱い" />
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
                {(preview.handover_suggestions.length > 0 || preview.handovers.length > 0) && <section className={sectionClass}>
                    <Heading step={4} title="取り置きへの引き継ぎ" note="自動の提案です。確認して必要なら直してください" />
                    <GoalHandovers preview={preview} chosen={options.handovers} accounts={accounts} currency={currency} busy={busy} onChange={(next) => choose('handovers', next)} />
                </section>}
                <section className={`${sectionClass} border-[var(--studio-accent)]`}>
                    <Heading step={preview.handover_suggestions.length > 0 || preview.handovers.length > 0 ? 5 : 4} title="予算の変更" note="「予算に反映する」でこの内容が保存されます" />
                    {changed.length ? <DataTable columns={['月', '項目', '口座', '現在', '反映後']}>
                        {changed.map((row, index) => <tr key={`change-${row.period}-${row.kind}-${row.line_id ?? index}`}>
                            <td className="whitespace-nowrap px-5 py-3">{row.kind === 'definition' ? `${row.period}以降の毎月` : row.period}</td>
                            <th scope="row" className="px-5 py-3 font-medium">{row.kind === 'retire' ? `${row.name}（以前の行を取り消す）` : row.kind === 'savings' ? 'ゴールの積立' : row.kind === 'definition' ? `定義：${row.name}` : row.kind === 'definition_row' ? `定義：${row.name}（保存済みの月）` : row.kind === 'claim' ? `確保：${row.name}（引き継ぎ）` : `取り置き：${row.name}`}
                                {row.kind === 'savings' && (row.includes_definitions ?? 0) > 0 && <span className="block text-xs font-normal text-[var(--studio-text-muted)]">この口座への定義 {formatCurrency(row.includes_definitions ?? 0, currency)} を含みます（予算では1行にまとまるため）</span>}</th>
                            <td className="px-5 py-3">{row.kind === 'capsule' && row.account_id === null ? '口座の指定なし' : accountName(row.account_id)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.current_amount === null ? '未設定' : formatCurrency(row.current_amount, currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.kind === 'retire' ? '削除' : formatCurrency(row.new_amount, currency)}</td>
                        </tr>)}
                    </DataTable> : <p className="text-sm text-[var(--studio-text-muted)]">予算は今の内容のままで、変更はありません。「反映を記録する」で、この内容に沿っていることを記録できます（お知らせと各ライフイベントの月額に使われます）。</p>}
                    <label className="flex items-start gap-2 border-t border-[var(--studio-border)] pt-3 text-sm">
                        <input type="checkbox" className="mt-1" disabled={busy} checked={updateBaseline} onChange={(event) => setUpdateBaseline(event.target.checked)} />
                        <span>基準線も今のゴールの予測で作り直す<span className="block text-xs text-[var(--studio-text-muted)]">実績と比べる基準線は、ゴールに採用したときのままです。計画を見直した場合に選んでください（以前の基準線は履歴に残ります）。</span></span>
                    </label>
                    {changed.some((row) => row.kind === 'definition') && <p role="note" className="text-xs text-[var(--studio-warning)]">定義の金額を書き換えると、反映する期間に関係なく以後の毎月の予算に使われ、定義から自動作成される取引の金額も変わります。</p>}
                </section>
            </>}
        </div>
    </Overlay>;
}
