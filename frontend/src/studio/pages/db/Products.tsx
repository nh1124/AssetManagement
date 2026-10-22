import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { createProduct, deleteProduct, getDepreciationSummary, getProducts,
         reserveConfirmation, updateProduct } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { DepreciationMethod, Product } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { ActiveSwitch, Choice, DataTable, EditableRow, EditorActions, Feedback, Field, OptionGroup, RowTitle } from './Database';
import { buttonClass, inputClass, loadLookups, useMutation, userCancelled } from './forms';
import { effectiveProductTreatment } from './productBudget';
import { labels, tr } from '../../i18n';

const loadProducts = (): Promise<Product[]> => getProducts();
type Lookups = Awaited<ReturnType<typeof loadLookups>>;
type FundingCapsule = Lookups['capsules'][number] & { life_event_id?: number | null };
type Treatment = NonNullable<Product['budget_treatment']>;
type Position = Awaited<ReturnType<typeof getDepreciationSummary>>['items'][number];
const loadPositions = () => getDepreciationSummary().then((summary) => summary.items);
// Module-level so the loader is stable: an inline one reloads on every render and,
// by re-rendering forever, keeps a route transition from ever committing.
const noPositions = async (): Promise<Position[]> => [];
const METHODS = labels<DepreciationMethod>({
    none: ['記帳しない', 'Not recorded'], straight_line: ['定額法', 'Straight line'], declining_balance: ['定率法', 'Declining balance'],
});
const treatments = (): Array<{ value: Treatment; label: string; description: string }> => [
    { value: 'auto', label: tr('自動', 'Automatic'), description: tr('固定資産は「固定資産の更新積立」、消耗品は購入周期 45 日以内なら「支出のみ」、それより長ければ「積立配分」になります。', 'Fixed assets use “Saving for replacement”; consumables bought every 45 days or less use “Expense only”, others “Saving allocation”.') },
    { value: 'expense_only', label: tr('支出のみ', 'Expense only'), description: tr('積み立てません。支出口座に毎月の支出予算として載ります。', 'Nothing is saved up. It appears as a monthly expense budget on the expense account.') },
    { value: 'reserve_allocation', label: tr('積立配分', 'Saving allocation'), description: tr('毎月（単価 × 30 ÷ 購入周期）を積立先の取り置きへ積み立て、購入時に取り崩します。', 'Saves (unit price × 30 ÷ purchase cycle) into the funding earmark every month and draws it down on purchase.') },
    { value: 'asset_replacement', label: tr('固定資産の更新積立', 'Saving for replacement'), description: tr('取得額を、更新予定日までの残り月数で割った額を毎月積み立てます（更新日が近いほど増えます）。', 'Saves the purchase price divided by the months left until replacement (more as replacement nears).') },
];
const help = () => ({
    budget: tr('この物品の購入を予算で計上する支出科目（費用の勘定科目）です。「支出のみ」のとき、この科目に毎月の予算行（単価 × 30 ÷ 購入周期）が出ます。積立の口座ではありません。', 'The expense account that budgets this item’s purchases. With “Expense only”, a monthly budget line (unit price × 30 ÷ purchase cycle) appears on it. It is not a savings account.'),
    funding: tr('買い替え・購入に備えて毎月積み立てる取り置きです。', 'The earmark saved into every month for buying or replacing the item.'),
    treatment: tr('この物品の費用を予算でどう扱うかです。各選択肢にカーソルを置くと説明が出ます。', 'How the budget treats this item’s cost. Hover over an option for details.'),
});

function replacementDate(product: Product) {
    if (!product.purchase_date || !product.lifespan_months || product.lifespan_months <= 0) return '—';
    const [year, month, day] = product.purchase_date.split('-').map(Number);
    // A useful-life estimate is not a stored purchase schedule; clamp month-end dates.
    const end = new Date(year, month - 1 + product.lifespan_months + 1, 0);
    const date = new Date(end.getFullYear(), end.getMonth(), Math.min(day, end.getDate()));
    return date.toLocaleDateString('sv-SE');
}

export function ProductEditor({ product, assets, currency, lookups, busy, onSave, onDelete, onCancel }: {
    product: Product | null; assets: boolean; currency: string; lookups: Lookups; busy: boolean;
    onSave: (attempt: (reserveFingerprint?: string) => Promise<unknown>) => void; onDelete?: () => void; onCancel: () => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const fundingCapsules = (lookups.capsules as FundingCapsule[]).filter((capsule) => capsule.life_event_id == null);
    const [name, setName] = useState(product?.name ?? '');
    // 'Uncategorized' is the stored placeholder for no category; the field shows it empty.
    const [category, setCategory] = useState(product?.category === 'Uncategorized' ? '' : product?.category ?? '');
    const [location, setLocation] = useState(product?.location ?? '');
    const [price, setPrice] = useState(product?.purchase_price == null ? '' : String(product.purchase_price));
    const [date, setDate] = useState(product?.purchase_date ?? '');
    const [lifespan, setLifespan] = useState(product?.lifespan_months == null ? '' : String(product.lifespan_months));
    // last_unit_price stores the purchase-unit price, despite its name; avoid rounding unit_cost back into it.
    const [purchaseUnitPrice, setPurchaseUnitPrice] = useState(String(product?.last_unit_price ?? 0));
    const [units, setUnits] = useState(String(product?.units_per_purchase ?? 1));
    const [frequency, setFrequency] = useState(String(product?.frequency_days ?? 0));
    const [lastPurchase, setLastPurchase] = useState(product?.last_purchase_date ?? '');
    const [budget, setBudget] = useState<number | null>(product?.budget_account_id ?? null);
    const [funding, setFunding] = useState<number | null>(product?.funding_capsule_id ?? null);
    const [treatment, setTreatment] = useState<Treatment>(product?.budget_treatment ?? 'auto');
    const [autoDepreciation, setAutoDepreciation] = useState(product?.auto_depreciation ?? false);
    const [method, setMethod] = useState<DepreciationMethod>(product?.depreciation_method ?? 'none');
    const [rate, setRate] = useState(product?.depreciation_annual_rate == null ? '' : String(product.depreciation_annual_rate));
    const [interval, setInterval] = useState<'monthly' | 'yearly'>(product?.depreciation_interval ?? 'monthly');
    const [startDate, setStartDate] = useState(product?.depreciation_start_date ?? '');
    const [expenseAccount, setExpenseAccount] = useState<number | null>(product?.depreciation_expense_account_id ?? null);
    const [assetAccount, setAssetAccount] = useState<number | null>(product?.depreciation_asset_account_id ?? null);
    const effectiveTreatment = effectiveProductTreatment(treatment, assets, Number(frequency));
    const expenseOnly = effectiveTreatment === 'expense_only';
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !name.trim()) return;
        if (assets && autoDepreciation && !product?.auto_depreciation
            && !(await confirm(tr('減価を自動で記帳しますか？期限を迎えた分は保存時に記帳されます。', 'Record depreciation automatically? Periods already due are recorded when you save.'), tr('保存して記帳する', 'Save and record')))) return;
        // Keep hidden choices locally; only send references used by this treatment.
        const payload = {
            name: name.trim(), category: category.trim() || 'Uncategorized', location: location.trim() || null,
            is_asset: assets, last_unit_price: assets ? product?.last_unit_price ?? Number(price) : Number(purchaseUnitPrice),
            units_per_purchase: assets ? product?.units_per_purchase ?? 1 : Number(units),
            frequency_days: assets ? product?.frequency_days ?? 0 : Number(frequency),
            last_purchase_date: assets ? product?.last_purchase_date ?? null : lastPurchase || null,
            purchase_price: assets ? price === '' ? null : Number(price) : product?.purchase_price ?? null,
            purchase_date: assets ? date || null : product?.purchase_date ?? null,
            lifespan_months: assets ? lifespan === '' ? null : Number(lifespan) : product?.lifespan_months ?? null,
            budget_account_id: expenseOnly ? budget : null, funding_capsule_id: expenseOnly ? null : funding, budget_treatment: treatment,
            // Only an asset is written down; a consumable keeps whatever it had.
            auto_depreciation: assets ? autoDepreciation : false,
            depreciation_method: assets ? method : product?.depreciation_method ?? 'none',
            depreciation_annual_rate: assets ? (rate === '' ? null : Number(rate)) : product?.depreciation_annual_rate ?? null,
            depreciation_interval: assets ? interval : product?.depreciation_interval ?? 'monthly',
            depreciation_start_date: assets ? (startDate || null) : product?.depreciation_start_date ?? null,
            depreciation_expense_account_id: assets ? expenseAccount : product?.depreciation_expense_account_id ?? null,
            depreciation_asset_account_id: assets ? assetAccount : product?.depreciation_asset_account_id ?? null,
        };
        onSave((fingerprint) => product ? updateProduct(product.id, payload, fingerprint) : createProduct(payload, fingerprint));
    };
    return <form id={formId} onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label={tr('物品名', 'Item')}><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('分類', 'Category')}><input value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('保管場所', 'Location')}><input value={location} onChange={(event) => setLocation(event.target.value)} className={inputClass} /></Field>
            {assets ? <>
                <Field label={tr(`取得額（${currency}）`, `Purchase price (${currency})`)}><input type="number" min="0" step="any" value={price} onChange={(event) => setPrice(event.target.value)} className={inputClass} /></Field>
                <Field label={tr('取得日', 'Purchase date')}><input type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field>
                <Field label={tr('耐用月数', 'Useful life (months)')}><input type="number" min="1" step="1" value={lifespan} onChange={(event) => setLifespan(event.target.value)} className={inputClass} /></Field>
                <div className="flex items-center gap-3 text-sm">{tr('減価を自動で記帳', 'Record depreciation automatically')}<ActiveSwitch name={tr('減価を自動で記帳', 'Record depreciation automatically')} active={autoDepreciation} disabled={busy} onToggle={() => setAutoDepreciation(!autoDepreciation)} /></div>
                <Field label={tr('減価の方法', 'Depreciation method')}><select value={method} onChange={(event) => setMethod(event.target.value as DepreciationMethod)} className={inputClass}>{Object.entries(METHODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                <div className={method === 'declining_balance' ? '' : 'invisible'}><Field label={tr('年償却率（％）', 'Annual rate (%)')}><input type="number" min="0" max="100" step="any" value={rate} onChange={(event) => setRate(event.target.value)} className={inputClass} disabled={method !== 'declining_balance'} /></Field></div>
                <fieldset disabled={!autoDepreciation} className={`grid gap-4 md:col-span-2 md:grid-cols-2 ${autoDepreciation ? '' : 'invisible'}`}>
                    <Field label={tr('記帳の間隔', 'Posting interval')}><select value={interval} onChange={(event) => setInterval(event.target.value as 'monthly' | 'yearly')} className={inputClass}><option value="monthly">{tr('毎月', 'Monthly')}</option><option value="yearly">{tr('毎年', 'Yearly')}</option></select></Field>
                    <Field label={tr('記帳の開始月（未設定なら取得日から）', 'First posting month (purchase date when empty)')}><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className={inputClass} /></Field>
                    <Choice label={tr('減価償却費の科目', 'Depreciation expense account')} value={expenseAccount} options={lookups.accounts} onChange={setExpenseAccount} />
                    <Choice label={tr('取り崩す物品の口座', 'Asset account written down')} value={assetAccount} options={lookups.accounts} onChange={setAssetAccount} />
                </fieldset>
            </> : <>
                <Field label={tr(`購入額（購入単位あたり・${currency}）`, `Price per purchase (${currency})`)}><input required type="number" min="0" step="any" value={purchaseUnitPrice} onChange={(event) => setPurchaseUnitPrice(event.target.value)} className={inputClass} /></Field>
                <Field label={tr('購入単位（個数）', 'Units per purchase')}><input required type="number" min="1" step="1" value={units} onChange={(event) => setUnits(event.target.value)} className={inputClass} /></Field>
                <Field label={tr('購入周期（日・0は不定期）', 'Purchase cycle (days, 0 = irregular)')}><input required type="number" min="0" step="1" value={frequency} onChange={(event) => setFrequency(event.target.value)} className={inputClass} /></Field>
                <Field label={tr('最終購入日', 'Last purchase')}><input type="date" value={lastPurchase} onChange={(event) => setLastPurchase(event.target.value)} className={inputClass} /></Field>
                <p className="text-xs text-[var(--studio-text-muted)] md:col-span-2">{tr('単価：', 'Unit price: ')}{formatCurrency(Number(purchaseUnitPrice) / (Number(units) || 1), currency)}</p>
            </>}
            <div className="md:col-span-2"><OptionGroup label={tr('予算での扱い', 'Budget treatment')} help={help().treatment} value={treatment} options={treatments()} onChange={setTreatment} />
                <p className={`mt-1 text-xs text-[var(--studio-text-muted)] ${treatment === 'auto' ? '' : 'invisible'}`}>{tr('自動：', 'Automatic: ')}{treatments().find((option) => option.value === effectiveTreatment)?.label}</p>
            </div>
            {expenseOnly
                ? <Choice label={tr('支出口座', 'Expense account')} help={help().budget} value={budget} options={lookups.accounts.filter((account) => account.account_type === 'expense')} onChange={setBudget} />
                : <Field label={tr('支出口座', 'Expense account')}><input disabled value={tr('この扱いでは使用しません', 'Not used with this treatment')} className={inputClass} /></Field>}
            {!expenseOnly
                ? <Choice label={tr('積立先の取り置き', 'Funding earmark')} help={help().funding} value={funding} options={fundingCapsules} onChange={setFunding} />
                : <Field label={tr('積立先の取り置き', 'Funding earmark')}><input disabled value={tr('この扱いでは使用しません', 'Not used with this treatment')} className={inputClass} /></Field>}
            <EditorActions form={formId} busy={busy} onCancel={onCancel} onDelete={onDelete} />
        </fieldset>
    </form>;
}

function ProductsForClient({ assets, currency }: { assets: boolean; currency: string }) {
    const confirm = useConfirm();
    const resource = useResource(loadProducts);
    const lookups = useResource(loadLookups);
    const positions = useResource(assets ? loadPositions : noPositions);
    const byProduct = new Map((positions.data ?? []).map((row) => [row.product_id, row]));
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ product: Product | null } | null>(null);
    const rows = resource.data?.filter((product) => assets ? product.is_asset : !product.is_asset) ?? [];
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy;
    const editorDisabled = disabled || lookups.loading || Boolean(lookups.error) || !lookups.data;
    // A save that moves an earmark's amounts is refused with the changes; show them and
    // repeat with the fingerprint only if the user agrees (again if they moved meanwhile).
    const withReserveCheck = async (attempt: (reserveFingerprint?: string) => Promise<unknown>, label: string) => {
        let fingerprint: string | undefined;
        for (;;) {
            try {
                return await attempt(fingerprint);
            } catch (failure: unknown) {
                const pending = reserveConfirmation(failure);
                if (!pending) throw failure;
                const lines = pending.changes.map((change) => tr(`取り置き「${change.name}」：目標額 ${formatCurrency(change.target_before, currency)} → ${formatCurrency(change.target_after, currency)}、`
                    + `月額 ${formatCurrency(change.monthly_before, currency)} → ${formatCurrency(change.monthly_after, currency)}`,
                `Earmark “${change.name}”: target ${formatCurrency(change.target_before, currency)} → ${formatCurrency(change.target_after, currency)}, `
                    + `monthly ${formatCurrency(change.monthly_before, currency)} → ${formatCurrency(change.monthly_after, currency)}`));
                if (!(await confirm(tr(`紐づく取り置きの金額が次のように変わります。\n\n${lines.join('\n')}`, `The linked earmarks change as follows.\n\n${lines.join('\n')}`), label, tr('取り置きの変更', 'Earmark changes')))) return userCancelled;
                fingerprint = pending.fingerprint;
            }
        }
    };
    const save = (attempt: (reserveFingerprint?: string) => Promise<unknown>) => void mutation.run(
        () => withReserveCheck(attempt, tr('変更して保存', 'Change and save')), tr('物品を保存しました。', 'Item saved.'),
        () => { setEditor(null); resource.reload(); positions.reload(); },
    );
    const remove = async (product: Product) => {
        if (disabled || !(await confirm(tr(`「${product.name}」を削除しますか？`, `Delete “${product.name}”?`), tr('削除する', 'Delete')))) return;
        void mutation.run(() => withReserveCheck((fingerprint) => deleteProduct(product.id, fingerprint), tr('削除する', 'Delete')), tr(`「${product.name}」を削除しました。`, `Deleted “${product.name}”.`), () => {
            setEditor(null);
            resource.setData((previous) => previous?.filter((row) => row.id !== product.id) ?? null);
            resource.reload();
        });
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2"><button type="button" disabled={editorDisabled || editor !== null} onClick={() => setEditor({ product: null })} className={buttonClass}>{tr('新規作成', 'New')}</button></div></div>
        <Feedback loading={resource.loading || lookups.loading || positions.loading} error={mutation.error || resource.error || lookups.error || positions.error} message={mutation.message} />
        {editor && lookups.data && <Overlay title={editor.product ? tr(`${editor.product.name}を編集`, `Edit ${editor.product.name}`) : assets ? tr('固定資産の新規作成', 'New fixed asset') : tr('消耗品の新規作成', 'New consumable')} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><ProductEditor key={editor.product?.id ?? 'new'} product={editor.product} assets={assets} currency={currency} lookups={lookups.data} busy={editorDisabled} onCancel={() => setEditor(null)} onSave={save} onDelete={editor.product ? () => void remove(editor.product as Product) : undefined} /></Overlay>}
        {resource.data && <DataTable columns={assets ? [tr('物品', 'Item'), tr('取得額', 'Purchase price'), tr('帳簿価額', 'Book value'), tr('減価の方法', 'Depreciation'), tr('次回の記帳', 'Next posting'), tr('更新予定', 'Replacement'), tr('積立先', 'Funding earmark'), tr('推奨月額', 'Suggested monthly')] : [tr('物品', 'Item'), tr('単価', 'Unit price'), tr('購入単位', 'Units per purchase'), tr('購入周期', 'Purchase cycle'), tr('支出口座', 'Expense account'), tr('積立先', 'Funding earmark'), tr('推奨月額', 'Suggested monthly')]}>
            {rows.length ? rows.map((row) => <EditableRow key={row.id} disabled={editorDisabled || editor !== null} onEdit={() => setEditor({ product: row })}>
                <RowTitle name={row.name} disabled={editorDisabled || editor !== null} onEdit={() => setEditor({ product: row })}>{row.name}<span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{row.category === 'Uncategorized' ? tr('未分類', 'Uncategorized') : row.category}</span></RowTitle>
                {assets ? <>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.purchase_price == null ? '—' : formatCurrency(row.purchase_price, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{byProduct.has(row.id) ? formatCurrency(byProduct.get(row.id)!.current_value, currency) : '—'}</td>
                    <td className="px-5 py-3">{METHODS[row.depreciation_method ?? 'none']}</td>
                    <td className="whitespace-nowrap px-5 py-3">{(() => {
                        const position = byProduct.get(row.id);
                        if (!position || position.method === 'none') return '—';
                        if (position.blocked_reason) return <span className="text-xs text-[var(--studio-text-muted)]">{position.blocked_reason}</span>;
                        if (!position.next_period) return '—';
                        return <>{position.next_period}<span className="ml-2 tabular-nums">{formatCurrency(position.monthly_depreciation, currency)}</span></>;
                    })()}</td>
                    <td className="whitespace-nowrap px-5 py-3">{replacementDate(row)}</td>
                </> : <>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.unit_cost, currency)}</td><td className="px-5 py-3">{tr(`${row.units_per_purchase}個`, `${row.units_per_purchase}`)}</td><td className="px-5 py-3">{row.frequency_days > 0 ? tr(`${row.frequency_days}日`, `${row.frequency_days} days`) : tr('不定期', 'Irregular')}</td><td className="px-5 py-3">{row.budget_account_name || (row.budget_account_id == null ? '—' : lookups.data?.accounts.find((account) => account.id === row.budget_account_id)?.name ?? `#${row.budget_account_id}`)}</td>
                </>}
                <td className="px-5 py-3">{row.funding_capsule_name || '—'}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.recommended_monthly_reserve ? formatCurrency(row.recommended_monthly_reserve, currency) : '—'}</td>
            </EditableRow>) : <tr><td colSpan={assets ? 8 : 7} className="px-5 py-4 text-[var(--studio-text-muted)]">{assets ? tr('登録された固定資産はありません。', 'No fixed assets.') : tr('登録された消耗品はありません。', 'No consumables.')}</td></tr>}
        </DataTable>}
    </section>;
}

export default function Products({ assets }: { assets: boolean }) {
    const { clientId, currentClient } = useClient();
    return <ProductsForClient key={`${clientId}:${assets}`} assets={assets}
        currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
