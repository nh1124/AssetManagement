import { useReloadAction } from '../../components/useReloadAction';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { createRegistryEntry, deleteRegistryEntry, getRegistryEntries, updateRegistryEntry } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { MonthlyPlanLineType, RegistryEntry, RegistryEntryType, RegistryFrequency } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Choice, DataTable, EditorActions, Feedback, Field, RowActions } from './Database';
import { buttonClass, inputClass, loadLookups, useMutation } from './forms';

type Tab = 'index' | 'income' | 'repayment' | 'allocation';
type Lookups = Awaited<ReturnType<typeof loadLookups>>;
type Draft = Pick<RegistryEntry,
    'name' | 'entry_type' | 'category' | 'amount' | 'currency' | 'frequency' | 'frequency_days' |
    'day_of_month' | 'month_of_year' | 'line_type' | 'budget_account_id' | 'source_account_id' |
    'destination_account_id' | 'funding_capsule_id' | 'budget_treatment' | 'generate_recurring' |
    'budget_active' | 'is_active' | 'source_product_id' | 'source_recurring_transaction_id' |
    'note' | 'start_period' | 'end_period'>;
const TYPES: Record<RegistryEntryType, string> = { service: 'サービス・継続支出', income: '収入', debt: '返済', allocation: '配分', asset: '固定資産', item: '消耗品' };
const FREQUENCIES: Record<RegistryFrequency, string> = { Monthly: '毎月', Yearly: '毎年', EveryNDays: '日数周期', Irregular: '不定期' };
const LINE_TYPES: Record<MonthlyPlanLineType, string> = { income: '収入', expense: '支出', allocation: '配分', debt_payment: '返済', borrowing: '借入', drawdown: '取り崩し' };
const DEFAULT_LINES: Record<RegistryEntryType, MonthlyPlanLineType> = { service: 'expense', income: 'income', debt: 'debt_payment', allocation: 'allocation', asset: 'allocation', item: 'expense' };
const TAB_TYPES: Record<Tab, RegistryEntryType> = { index: 'service', income: 'income', repayment: 'debt', allocation: 'allocation' };

function entryTab(entry: RegistryEntry): Tab {
    // entry_type is the registry's semantic discriminator; line_type describes budget treatment.
    if (entry.entry_type === 'income') return 'income';
    if (entry.entry_type === 'debt') return 'repayment';
    if (entry.entry_type === 'allocation') return 'allocation';
    // Product-backed asset and item definitions stay visible on the index tab.
    return 'index';
}

function toDraft(entry: RegistryEntry | null, currency: string, type: RegistryEntryType): Draft {
    // PUT replaces the entry; preserve source links without sending read-only response fields.
    return {
        name: entry?.name ?? '', entry_type: entry?.entry_type ?? type, category: entry?.category ?? null,
        amount: entry?.amount ?? 0, currency: entry?.currency ?? currency,
        frequency: entry?.frequency ?? 'Monthly', frequency_days: entry?.frequency_days ?? null,
        day_of_month: entry?.day_of_month ?? 1, month_of_year: entry?.month_of_year ?? null,
        line_type: entry?.line_type ?? DEFAULT_LINES[type], budget_account_id: entry?.budget_account_id ?? null,
        source_account_id: entry?.source_account_id ?? null, destination_account_id: entry?.destination_account_id ?? null,
        funding_capsule_id: entry?.funding_capsule_id ?? null, budget_treatment: entry?.budget_treatment ?? 'expense_only',
        generate_recurring: entry?.generate_recurring ?? false, budget_active: entry?.budget_active ?? true,
        is_active: entry?.is_active ?? true, source_product_id: entry?.source_product_id ?? null,
        source_recurring_transaction_id: entry?.source_recurring_transaction_id ?? null,
        note: entry?.note ?? null, start_period: entry?.start_period ?? null, end_period: entry?.end_period ?? null,
    };
}

function schedule(entry: RegistryEntry) {
    switch (entry.frequency) {
        case 'Monthly': return `毎月 ${entry.day_of_month}日`;
        case 'Yearly': return `毎年 ${entry.month_of_year ?? 1}月${entry.day_of_month}日`;
        case 'EveryNDays': return entry.frequency_days ? `${entry.frequency_days}日ごと` : '日数周期（未設定）';
        case 'Irregular': return '不定期';
    }
}

function DefinitionEditor({ entry, type, currency, lookups, busy, onSave, onCancel }: {
    entry: RegistryEntry | null; type: RegistryEntryType; currency: string; lookups: Lookups; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [form, setForm] = useState(() => toDraft(entry, currency, type));
    const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setForm((previous) => ({ ...previous, [key]: value }));
    const scheduled = form.frequency === 'Monthly' || form.frequency === 'Yearly';
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !form.name.trim()) return;
        onSave(() => {
            if (form.start_period && form.end_period && form.start_period > form.end_period) throw new Error('終了月は開始月以降にしてください。');
            if (form.generate_recurring && !scheduled) throw new Error('自動記帳の周期は毎月または毎年にしてください。');
            const payload: Draft = {
                ...form, name: form.name.trim(), category: form.category?.trim() || null, note: form.note?.trim() || null,
                frequency_days: form.frequency === 'EveryNDays' ? form.frequency_days : null,
                month_of_year: form.frequency === 'Yearly' ? form.month_of_year ?? 1 : null,
            };
            return entry ? updateRegistryEntry(entry.id, payload) : createRegistryEntry(payload);
        });
    };
    return <form id={formId} onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={form.name} onChange={(event) => set('name', event.target.value)} className={inputClass} /></Field>
            <Field label="定義の種別"><select value={form.entry_type} onChange={(event) => { const next = event.target.value as RegistryEntryType; setForm((previous) => ({ ...previous, entry_type: next, line_type: DEFAULT_LINES[next] })); }} className={inputClass}>{Object.entries(TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label={`金額（${form.currency}）`}><input required type="number" min={form.generate_recurring ? '0.00000001' : '0'} step="any" value={form.amount} onChange={(event) => set('amount', Number(event.target.value))} className={inputClass} /></Field>
            <Field label="通貨"><input required pattern="[A-Z]{3}" maxLength={3} value={form.currency} onChange={(event) => set('currency', event.target.value.toUpperCase())} className={inputClass} /></Field>
            <Field label="周期"><select value={form.frequency} onChange={(event) => set('frequency', event.target.value as RegistryFrequency)} className={inputClass}>{Object.entries(FREQUENCIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            {scheduled && <Field label="予定日（日）"><input required type="number" min="1" max="31" step="1" value={form.day_of_month} onChange={(event) => set('day_of_month', Number(event.target.value))} className={inputClass} /></Field>}
            {form.frequency === 'Yearly' && <Field label="予定月"><input required type="number" min="1" max="12" step="1" value={form.month_of_year ?? 1} onChange={(event) => set('month_of_year', Number(event.target.value))} className={inputClass} /></Field>}
            {form.frequency === 'EveryNDays' && <Field label="周期の日数"><input required type="number" min="1" step="1" value={form.frequency_days ?? ''} onChange={(event) => set('frequency_days', event.target.value ? Number(event.target.value) : null)} className={inputClass} /></Field>}
            <Choice label="予算口座" value={form.budget_account_id} options={lookups.accounts} onChange={(value) => set('budget_account_id', value)} />
            <Choice label="出金元・収入科目" value={form.source_account_id} options={lookups.accounts} required={form.generate_recurring} onChange={(value) => set('source_account_id', value)} />
            <Choice label="入金先・支出科目・返済先" value={form.destination_account_id} options={lookups.accounts} required={form.generate_recurring && !form.budget_account_id} onChange={(value) => set('destination_account_id', value)} />
            <Choice label="積立先の取り置き" value={form.funding_capsule_id} options={lookups.capsules} onChange={(value) => set('funding_capsule_id', value)} />
            <div className="space-y-3 text-sm md:col-span-2">
                <label className="flex items-center gap-2"><input type="checkbox" checked={form.generate_recurring} disabled={!scheduled && !form.generate_recurring} onChange={(event) => setForm((previous) => ({ ...previous, generate_recurring: event.target.checked, budget_active: event.target.checked || previous.budget_active }))} />定義から自動記帳する（毎月・毎年）</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={form.budget_active} disabled={form.generate_recurring} onChange={(event) => set('budget_active', event.target.checked)} />予算に反映する</label>
                {form.generate_recurring && <p className="text-xs text-[var(--studio-text-muted)]">自動記帳する定義は予算にも反映されます。</p>}
                <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_active} onChange={(event) => set('is_active', event.target.checked)} />定義を有効にする</label>
            </div>
            <details className="md:col-span-2"><summary className="cursor-pointer text-sm text-[var(--studio-text-muted)]">詳細設定</summary><div className="mt-4 grid gap-4 md:grid-cols-2">
                <Field label="予算の行種別"><select value={form.line_type} onChange={(event) => set('line_type', event.target.value as MonthlyPlanLineType)} className={inputClass}>{Object.entries(LINE_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                <Field label="予算での扱い"><select value={form.budget_treatment} onChange={(event) => set('budget_treatment', event.target.value as Draft['budget_treatment'])} className={inputClass}><option value="auto">自動</option><option value="expense_only">支出のみ</option><option value="reserve_allocation">積立配分</option><option value="asset_replacement">固定資産の更新積立</option></select></Field>
                <Field label="分類"><input value={form.category ?? ''} onChange={(event) => set('category', event.target.value)} className={inputClass} /></Field>
                <Field label="開始月"><input type="month" value={form.start_period ?? ''} onChange={(event) => set('start_period', event.target.value || null)} className={inputClass} /></Field>
                <Field label="終了月"><input type="month" min={form.start_period || undefined} value={form.end_period ?? ''} onChange={(event) => set('end_period', event.target.value || null)} className={inputClass} /></Field>
                <Field label="メモ"><textarea value={form.note ?? ''} onChange={(event) => set('note', event.target.value)} className={inputClass} /></Field>
            </div></details>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

function DefinitionsForClient({ tab, currency }: { tab: Tab; currency: string }) {
    const confirm = useConfirm();
    const resource = useResource(getRegistryEntries);
    const lookups = useResource(loadLookups);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ entry: RegistryEntry | null } | null>(null);
    const rows = resource.data?.filter((entry) => entryTab(entry) === tab) ?? [];
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy;
    const editorDisabled = disabled || lookups.loading || Boolean(lookups.error) || !lookups.data;
    const remove = async (entry: RegistryEntry) => {
        if (disabled || !(await confirm(`「${entry.name}」の定義を削除しますか？`, '削除する'))) return;
        void mutation.run(() => deleteRegistryEntry(entry.id), `「${entry.name}」の削除処理が完了しました。`, resource.reload);
    };
    const accountName = (id: number | null | undefined, name?: string | null) => name || (id == null ? '—' : lookups.data?.accounts.find((row) => row.id === id)?.name ?? `#${id}`);
    useReloadAction(() => { resource.reload(); lookups.reload(); }, Boolean(resource.loading || lookups.loading || mutation.busy || editor !== null));
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2"><button type="button" disabled={editorDisabled || editor !== null} onClick={() => setEditor({ entry: null })} className={buttonClass}>新規作成</button></div></div>
        <Feedback loading={resource.loading || lookups.loading} error={mutation.error || resource.error || lookups.error} message={mutation.message} />
        {editor && lookups.data && <Overlay title={editor.entry ? `${editor.entry.name}を編集` : '定義の新規作成'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><DefinitionEditor key={editor.entry?.id ?? 'new'} entry={editor.entry} type={TAB_TYPES[tab]} currency={currency} lookups={lookups.data} busy={editorDisabled} onCancel={() => setEditor(null)} onSave={(action) => void mutation.run(action, '定義を保存しました。', () => { setEditor(null); resource.reload(); })} /></Overlay>}
        {resource.data && <DataTable columns={['名称', '周期・予定日', '金額', '口座', '予算に反映するか', '操作']}>
            {rows.length ? rows.map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-medium">{row.name}<span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{TYPES[row.entry_type]}{!row.is_active && '・無効'}</span></th>
                <td className="whitespace-nowrap px-5 py-3">{schedule(row)}{(row.start_period || row.end_period) && <span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{row.start_period || '開始未設定'} 〜 {row.end_period || '終了未設定'}</span>}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.amount, row.currency || currency)} <span className="text-xs text-[var(--studio-text-muted)]">{row.currency || currency}</span></td>
                <td className="px-5 py-3"><p>{accountName(row.source_account_id, row.source_account_name)} → {accountName(row.destination_account_id, row.destination_account_name)}</p><p className="mt-1 text-xs text-[var(--studio-text-muted)]">予算：{accountName(row.budget_account_id, row.budget_account_name)}</p></td>
                <td className="px-5 py-3">{row.budget_active ? row.is_active ? '反映する' : '反映する（定義は無効）' : '反映しない'}</td>
                <RowActions name={row.name} disabled={editorDisabled || editor !== null} onEdit={() => setEditor({ entry: row })} onDelete={() => remove(row)} />
            </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">このタブの定義はありません。</td></tr>}
        </DataTable>}
    </section>;
}

export default function Definitions({ tab = 'index' }: { tab?: Tab }) {
    const { clientId, currentClient } = useClient();
    return <DefinitionsForClient key={`${clientId}:${tab}`} tab={tab} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
