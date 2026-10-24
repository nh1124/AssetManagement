import { useCallback, useContext, useId, useState, type FormEvent, type ReactNode } from 'react';
import { amendDepreciation, getAccounts, getDepreciationPreview, getProducts, recordDepreciation } from '../../api';
import type { DepreciationPreview, Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';
import { OverlayFooter } from '../components/Overlay';
import { OverlayFooterContext } from '../components/overlayContext';
import { assetErrorMessage, useResource } from '../useResource';
import { Feedback, Field } from './db/Database';
import { buttonClass, inputClass, primaryClass } from './db/forms';
import { tr } from '../i18n';

/** A period is written down on its last day. */
function periodEnd(period: string): string {
    const [year, month] = period.split('-').map(Number);
    const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return `${period}-${String(last).padStart(2, '0')}`;
}

async function loadChoices() {
    const [products, accounts] = await Promise.all([getProducts(), getAccounts()]);
    return { assets: products.filter((product) => product.is_asset), accounts };
}

/** 減価償却 in the ledger (R2): pick the fixed asset and the expense; the schedule proposes the period and amount. */
export default function DepreciationForm({ existing, kindSelect, onSaved, onCancel, onDelete, deleting = false }: {
    existing?: Transaction; kindSelect?: ReactNode; onSaved?: () => void; onCancel?: () => void; onDelete?: () => void; deleting?: boolean;
}) {
    const formId = useId();
    const inOverlay = useContext(OverlayFooterContext) !== undefined;
    const choices = useResource(loadChoices);
    const record = existing?.depreciation ?? null;
    const [productId, setProductId] = useState<number | null>(record?.product_id ?? null);
    const [preview, setPreview] = useState<DepreciationPreview | null>(null);
    const [period, setPeriod] = useState(record?.period ?? '');
    const [amount, setAmount] = useState(existing ? String(existing.amount) : '');
    const [date, setDate] = useState(existing?.date ?? '');
    const [expenseId, setExpenseId] = useState<number | null>(existing?.legs?.find((leg) => (leg.debit ?? 0) > 0)?.account_id ?? null);
    const [assetId, setAssetId] = useState<number | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const expenses = choices.data?.accounts.filter((account) => account.account_type === 'expense') ?? [];
    const assetAccounts = choices.data?.accounts.filter((account) => account.account_type === 'asset') ?? [];
    const currency = existing?.currency ?? preview?.currency ?? 'JPY';

    const choose = useCallback(async (id: number | null) => {
        setProductId(id);
        setPreview(null);
        setError('');
        if (id === null) return;
        try {
            const next = await getDepreciationPreview(id);
            setPreview(next);
            setPeriod(next.next_period ?? '');
            setAmount(next.due > 0 ? String(next.due) : '');
            setDate(next.next_period ? periodEnd(next.next_period) : '');
            setExpenseId(next.expense_account_id);
            setAssetId(next.asset_account_id);
        } catch (failure: unknown) {
            setError(assetErrorMessage(failure));
        }
    }, []);

    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const value = Number(amount);
        if (busy || deleting) return;
        if (!productId || !/^\d{4}-(0[1-9]|1[0-2])$/.test(period) || !Number.isFinite(value) || value <= 0 || !date || !expenseId || (!record && !assetId)) {
            setError(tr('固定資産・対象期・金額・日付・費用科目を入力してください。', 'Enter the fixed asset, period, amount, date and expense account.'));
            return;
        }
        setBusy(true);
        setError('');
        setMessage('');
        try {
            if (record) {
                await amendDepreciation(record.id, { amount: value, date, expense_account_id: expenseId });
                onSaved?.();
                return;
            }
            await recordDepreciation({ product_id: productId, period, amount: value, date, expense_account_id: expenseId, asset_account_id: assetId });
            setMessage(tr(`減価償却（${period}）を記録しました。`, `Depreciation for ${period} recorded.`));
            await choose(productId);
        } catch (failure: unknown) {
            setError(assetErrorMessage(failure));
        } finally {
            setBusy(false);
        }
    };

    const save = <button type="submit" form={formId} disabled={busy || deleting || choices.loading} className={primaryClass}>{busy ? tr('保存しています…', 'Saving…') : record ? tr('保存', 'Save') : tr('記録する', 'Record')}</button>;
    return <section className={inOverlay ? 'w-full' : 'mx-auto w-full max-w-xl rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6'}>
        <form id={formId} onSubmit={submit} className="space-y-5">
            <Feedback loading={choices.loading} error={choices.error || error} message={message} />
            {kindSelect}
            <fieldset disabled={busy || deleting || choices.loading} className="space-y-5">
                {record ? <p className="text-sm">{tr(`固定資産「${record.product_name ?? `#${record.product_id}`}」の ${record.period} の減価償却`, `Depreciation of the fixed asset “${record.product_name ?? `#${record.product_id}`}” for ${record.period}`)}</p> : <>
                    <Field label={tr('固定資産', 'Fixed asset')}><select required value={productId ?? ''} onChange={(changed) => { void choose(changed.target.value ? Number(changed.target.value) : null); }} className={inputClass}>
                        <option value="">{tr('選択してください', 'Choose…')}</option>
                        {choices.data?.assets.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
                    </select></Field>
                    {preview && <p className="text-xs text-[var(--studio-text-muted)]">{tr('帳簿価額', 'Book value')} {formatCurrency(preview.book_value, currency)}{preview.blocked_reason ? tr(`（自動の計算：${preview.blocked_reason}）`, ` (automatic calculation: ${preview.blocked_reason})`) : ''}</p>}
                    <Field label={tr('対象期', 'Period')} help={tr('同じ期は二度記帳できません。空いている最初の期を表示しています。', 'A period can be recorded only once. The first open period is shown.')}><input required type="month" value={period} onChange={(changed) => { setPeriod(changed.target.value); if (changed.target.value) setDate(periodEnd(changed.target.value)); }} className={inputClass} /></Field>
                </>}
                <Field label={tr(`金額（${currency}）`, `Amount (${currency})`)}><input required type="number" min="0.01" step="any" value={amount} onChange={(changed) => setAmount(changed.target.value)} className={inputClass} /></Field>
                <Field label={tr('日付', 'Date')}><input required type="date" value={date} onChange={(changed) => setDate(changed.target.value)} className={inputClass} /></Field>
                <Field label={tr('費用科目', 'Expense account')}><select required value={expenseId ?? ''} onChange={(changed) => setExpenseId(changed.target.value ? Number(changed.target.value) : null)} className={inputClass}>
                    <option value="">{tr('選択してください', 'Choose…')}</option>
                    {expenses.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                </select></Field>
                {!record && productId !== null && preview && !preview.asset_account_id && <Field label={tr('固定資産の口座', 'Fixed asset account')} help={tr('この固定資産に保存し、次からは選ばなくて済みます。', 'Saved on this fixed asset, so you will not need to choose it next time.')}><select required value={assetId ?? ''} onChange={(changed) => setAssetId(changed.target.value ? Number(changed.target.value) : null)} className={inputClass}>
                    <option value="">{tr('選択してください', 'Choose…')}</option>
                    {assetAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                </select></Field>}
            </fieldset>
            <OverlayFooter fallback={<div className="flex gap-2">{save}{onCancel && <button type="button" onClick={onCancel} className={buttonClass}>{tr('キャンセル', 'Cancel')}</button>}</div>}>
                {onDelete && <button type="button" disabled={busy || deleting} onClick={onDelete} className={`${buttonClass} mr-auto text-[var(--studio-danger)]`}>{deleting ? tr('削除中…', 'Deleting…') : tr('削除', 'Delete')}</button>}
                {save}
            </OverlayFooter>
        </form>
    </section>;
}
