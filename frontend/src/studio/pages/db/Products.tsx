import { useReloadAction } from '../../components/useReloadAction';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { createProduct, deleteProduct, getDepreciationSummary, getProducts, postDepreciation,
         runDepreciation, updateProduct } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { DepreciationMethod, Product } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { clientToday } from '../../datetime';
import { Choice, DataTable, EditorActions, Feedback, Field, RowActions } from './Database';
import { buttonClass, inputClass, loadLookups, useMutation } from './forms';

const loadProducts = (): Promise<Product[]> => getProducts();
type Lookups = Awaited<ReturnType<typeof loadLookups>>;
type Treatment = NonNullable<Product['budget_treatment']>;
type Position = Awaited<ReturnType<typeof getDepreciationSummary>>['items'][number];
const loadPositions = () => getDepreciationSummary().then((summary) => summary.items);
const METHODS: Record<DepreciationMethod, string> = {
    none: '記帳しない', straight_line: '定額法', declining_balance: '定率法',
};
const TREATMENTS: Record<Treatment, string> = { auto: '自動', expense_only: '支出のみ', reserve_allocation: '積立配分', asset_replacement: '固定資産の更新積立' };

function replacementDate(product: Product) {
    if (!product.purchase_date || !product.lifespan_months || product.lifespan_months <= 0) return '—';
    const [year, month, day] = product.purchase_date.split('-').map(Number);
    // A useful-life estimate is not a stored purchase schedule; clamp month-end dates.
    const end = new Date(year, month - 1 + product.lifespan_months + 1, 0);
    const date = new Date(end.getFullYear(), end.getMonth(), Math.min(day, end.getDate()));
    return date.toLocaleDateString('sv-SE');
}

function ProductEditor({ product, assets, currency, lookups, busy, onSave, onCancel }: {
    product: Product | null; assets: boolean; currency: string; lookups: Lookups; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [name, setName] = useState(product?.name ?? '');
    const [category, setCategory] = useState(product?.category ?? '');
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
    const [method, setMethod] = useState<DepreciationMethod>(product?.depreciation_method ?? 'none');
    const [rate, setRate] = useState(product?.depreciation_annual_rate == null ? '' : String(product.depreciation_annual_rate));
    const [interval, setInterval] = useState<'monthly' | 'yearly'>(product?.depreciation_interval ?? 'monthly');
    const [startDate, setStartDate] = useState(product?.depreciation_start_date ?? '');
    const [expenseAccount, setExpenseAccount] = useState<number | null>(product?.depreciation_expense_account_id ?? null);
    const [assetAccount, setAssetAccount] = useState<number | null>(product?.depreciation_asset_account_id ?? null);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !name.trim()) return;
        // PUT replaces the product, so retain hidden fields and send no derived response values.
        const payload = {
            name: name.trim(), category: category.trim() || 'Uncategorized', location: location.trim() || null,
            is_asset: assets, last_unit_price: assets ? product?.last_unit_price ?? Number(price) : Number(purchaseUnitPrice),
            units_per_purchase: assets ? product?.units_per_purchase ?? 1 : Number(units),
            frequency_days: assets ? product?.frequency_days ?? 0 : Number(frequency),
            last_purchase_date: assets ? product?.last_purchase_date ?? null : lastPurchase || null,
            purchase_price: assets ? price === '' ? null : Number(price) : product?.purchase_price ?? null,
            purchase_date: assets ? date || null : product?.purchase_date ?? null,
            lifespan_months: assets ? lifespan === '' ? null : Number(lifespan) : product?.lifespan_months ?? null,
            budget_account_id: budget, funding_capsule_id: funding, budget_treatment: treatment,
            // Only an asset is written down; a consumable keeps whatever it had.
            depreciation_method: assets ? method : product?.depreciation_method ?? 'none',
            depreciation_annual_rate: assets ? (rate === '' ? null : Number(rate)) : product?.depreciation_annual_rate ?? null,
            depreciation_interval: assets ? interval : product?.depreciation_interval ?? 'monthly',
            depreciation_start_date: assets ? (startDate || null) : product?.depreciation_start_date ?? null,
            depreciation_expense_account_id: assets ? expenseAccount : product?.depreciation_expense_account_id ?? null,
            depreciation_asset_account_id: assets ? assetAccount : product?.depreciation_asset_account_id ?? null,
        };
        onSave(() => product ? updateProduct(product.id, payload) : createProduct(payload));
    };
    return <form id={formId} onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="物品名"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label="分類"><input value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass} /></Field>
            <Field label="保管場所"><input value={location} onChange={(event) => setLocation(event.target.value)} className={inputClass} /></Field>
            {assets ? <>
                <Field label={`取得額（${currency}）`}><input type="number" min="0" step="any" value={price} onChange={(event) => setPrice(event.target.value)} className={inputClass} /></Field>
                <Field label="取得日"><input type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field>
                <Field label="耐用月数"><input type="number" min="1" step="1" value={lifespan} onChange={(event) => setLifespan(event.target.value)} className={inputClass} /></Field>
                <Field label="減価の方法"><select value={method} onChange={(event) => setMethod(event.target.value as DepreciationMethod)} className={inputClass}>{Object.entries(METHODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                {method === 'declining_balance' && <Field label="年償却率（％）"><input type="number" min="0" max="100" step="any" value={rate} onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>}
                {method !== 'none' && <>
                    <Field label="記帳の間隔"><select value={interval} onChange={(event) => setInterval(event.target.value as 'monthly' | 'yearly')} className={inputClass}><option value="monthly">毎月</option><option value="yearly">毎年</option></select></Field>
                    <Field label="記帳の開始月（未設定なら取得日から）"><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className={inputClass} /></Field>
                    <Choice label="減価償却費の科目" value={expenseAccount} options={lookups.accounts} onChange={setExpenseAccount} />
                    <Choice label="取り崩す物品の口座" value={assetAccount} options={lookups.accounts} onChange={setAssetAccount} />
                </>}
            </> : <>
                <Field label={`購入額（購入単位あたり・${currency}）`}><input required type="number" min="0" step="any" value={purchaseUnitPrice} onChange={(event) => setPurchaseUnitPrice(event.target.value)} className={inputClass} /></Field>
                <Field label="購入単位（個数）"><input required type="number" min="1" step="1" value={units} onChange={(event) => setUnits(event.target.value)} className={inputClass} /></Field>
                <Field label="購入周期（日・0は不定期）"><input required type="number" min="0" step="1" value={frequency} onChange={(event) => setFrequency(event.target.value)} className={inputClass} /></Field>
                <Field label="最終購入日"><input type="date" value={lastPurchase} onChange={(event) => setLastPurchase(event.target.value)} className={inputClass} /></Field>
                <p className="text-xs text-[var(--studio-text-muted)] md:col-span-2">単価：{formatCurrency(Number(purchaseUnitPrice) / (Number(units) || 1), currency)}</p>
            </>}
            <Choice label="予算口座" value={budget} options={lookups.accounts} onChange={setBudget} />
            <Choice label="積立先の取り置き" value={funding} options={lookups.capsules} onChange={setFunding} />
            <Field label="予算での扱い"><select value={treatment} onChange={(event) => setTreatment(event.target.value as Treatment)} className={inputClass}>{Object.entries(TREATMENTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

function ProductsForClient({ assets, currency, timezone }: { assets: boolean; currency: string; timezone: string }) {
    const confirm = useConfirm();
    const resource = useResource(loadProducts);
    const lookups = useResource(loadLookups);
    const positions = useResource(assets ? loadPositions : async () => [] as Position[]);
    const byProduct = new Map((positions.data ?? []).map((row) => [row.product_id, row]));
    const period = clientToday(timezone).slice(0, 7);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ product: Product | null } | null>(null);
    const rows = resource.data?.filter((product) => assets ? product.is_asset : !product.is_asset) ?? [];
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy;
    const editorDisabled = disabled || lookups.loading || Boolean(lookups.error) || !lookups.data;
    const write = async (product: Product) => {
        const position = byProduct.get(product.id);
        if (disabled || !position?.next_period) return;
        const amount = formatCurrency(position.monthly_depreciation, currency);
        // The confirm names both sides: this posts an entry, not a label.
        const ok = await confirm(
            `「${product.name}」の${position.next_period}分として${amount}を記帳しますか？\n`
            + '減価償却費を借方、物品の口座を貸方に立てます。',
            '記帳する',
        );
        if (!ok) return;
        void mutation.run(
            () => postDepreciation(product.id, position.next_period as string),
            `「${product.name}」の${position.next_period}分を記帳しました。`,
            () => { resource.reload(); positions.reload(); },
        );
    };
    const writeMonth = async () => {
        if (disabled || !(await confirm(
            `${period}分の減価を、次の記帳月がこの月の固定資産すべてに記帳しますか？\n`
            + '記帳できないものは理由とともに報告します。',
            '記帳する',
        ))) return;
        void mutation.run(async () => {
            const result = await runDepreciation(period);
            return result;
        }, `${period}分を記帳しました。`, () => { resource.reload(); positions.reload(); });
    };
    const remove = async (product: Product) => {
        if (disabled || !(await confirm(`「${product.name}」を削除しますか？`, '削除する'))) return;
        void mutation.run(() => deleteProduct(product.id), `「${product.name}」を削除しました。`, () => {
            resource.setData((previous) => previous?.filter((row) => row.id !== product.id) ?? null);
            resource.reload();
        });
    };
    useReloadAction(() => { resource.reload(); lookups.reload(); }, Boolean(resource.loading || lookups.loading || mutation.busy || editor !== null));
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2">{assets && <button type="button" disabled={editorDisabled || editor !== null} onClick={() => void writeMonth()} className={buttonClass}>{period}分を記帳</button>}<button type="button" disabled={editorDisabled || editor !== null} onClick={() => setEditor({ product: null })} className={buttonClass}>新規作成</button></div></div>
        {assets && <p className="text-xs text-[var(--studio-text-muted)]">更新予定は目安です。</p>}
        <Feedback loading={resource.loading || lookups.loading || positions.loading} error={mutation.error || resource.error || lookups.error || positions.error} message={mutation.message} />
        {editor && lookups.data && <Overlay title={editor.product ? `${editor.product.name}を編集` : `${assets ? '固定資産' : '消耗品'}の新規作成`} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><ProductEditor key={editor.product?.id ?? 'new'} product={editor.product} assets={assets} currency={currency} lookups={lookups.data} busy={editorDisabled} onCancel={() => setEditor(null)} onSave={(action) => void mutation.run(action, '物品を保存しました。', () => { setEditor(null); resource.reload(); positions.reload(); })} /></Overlay>}
        {resource.data && <DataTable columns={assets ? ['物品', '取得額', '帳簿価額', '減価の方法', '次回の記帳', '更新予定', '操作'] : ['物品', '単価', '購入単位', '購入周期', '予算口座', '操作']}>
            {rows.length ? rows.map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-medium">{row.name}<span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{row.category === 'Uncategorized' ? '未分類' : row.category}</span></th>
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
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.unit_cost, currency)}</td><td className="px-5 py-3">{row.units_per_purchase}個</td><td className="px-5 py-3">{row.frequency_days > 0 ? `${row.frequency_days}日` : '不定期'}</td><td className="px-5 py-3">{row.budget_account_name || (row.budget_account_id == null ? '—' : lookups.data?.accounts.find((account) => account.id === row.budget_account_id)?.name ?? `#${row.budget_account_id}`)}</td>
                </>}
                {assets && <td className="px-5 py-3"><button type="button"
                    disabled={disabled || editor !== null || !byProduct.get(row.id)?.next_period || Boolean(byProduct.get(row.id)?.blocked_reason)}
                    onClick={() => void write(row)} className={buttonClass}>記帳する</button></td>}
                <RowActions name={row.name} disabled={editorDisabled || editor !== null} onEdit={() => setEditor({ product: row })} onDelete={() => remove(row)} />
            </tr>) : <tr><td colSpan={assets ? 8 : 6} className="px-5 py-4 text-[var(--studio-text-muted)]">登録された{assets ? '固定資産' : '消耗品'}はありません。</td></tr>}
        </DataTable>}
    </section>;
}

export default function Products({ assets }: { assets: boolean }) {
    const { clientId, currentClient } = useClient();
    return <ProductsForClient key={`${clientId}:${assets}`} assets={assets}
        currency={currentClient?.general_settings?.currency || 'JPY'}
        timezone={currentClient?.general_settings?.timezone || 'UTC'} />;
}
