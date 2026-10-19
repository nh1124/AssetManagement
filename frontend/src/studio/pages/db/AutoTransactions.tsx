import { useState } from 'react';
import { createAutoTransaction, deleteAutoTransaction, deleteProduct, getAutoTransactions, getAutomaticDepreciation, getProducts, reserveConfirmation, updateAutoTransaction } from '../../../api';
import type { AutoTransaction, AutoTransactionInput, AutoTransactionKind, Product } from '../../../types';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { DataTable, EditableRow, Feedback, RowTitle } from './Database';
import { buttonClass, loadLookups, useMutation, userCancelled } from './forms';
import { ProductEditor } from './Products';
import AutoTransactionEditor from './AutoTransactionEditor';
import { scheduleLabel } from './automaticSchedule';

type Tab = 'index' | 'income' | 'repayment' | 'allocation';
const TAB_KIND: Record<Tab, AutoTransactionKind> = { index: 'expense', income: 'income', repayment: 'debt', allocation: 'transfer' };
const loadProducts = () => getProducts();

function AutoTransactionsForClient({ tab, currency }: { tab: Tab; currency: string }) {
    const resource = useResource(getAutoTransactions);
    const lookups = useResource(loadLookups);
    const depreciation = useResource(getAutomaticDepreciation);
    const products = useResource(loadProducts);
    const mutation = useMutation();
    const confirm = useConfirm();
    const [editor, setEditor] = useState<{ entry: AutoTransaction | null } | null>(null);
    const [product, setProduct] = useState<Product | null>(null);
    const disabled = mutation.busy || resource.loading || lookups.loading || Boolean(resource.error || lookups.error) || !lookups.data;
    const done = () => { setEditor(null); setProduct(null); resource.reload(); depreciation.reload(); products.reload(); };
    const save = (form: AutoTransactionInput) => void mutation.run(() => editor?.entry ? updateAutoTransaction(editor.entry.id, form) : createAutoTransaction(form), '保存しました。', done);
    const remove = async () => {
        if (!editor?.entry || !(await confirm(`「${editor.entry.name}」を削除しますか？`, '削除する'))) return;
        void mutation.run(() => deleteAutoTransaction(editor.entry!.id), '削除しました。', done);
    };
    const saveProduct = (attempt: (fingerprint?: string) => Promise<unknown>, message = '保存しました。') => void mutation.run(async () => {
        let fingerprint: string | undefined;
        for (;;) {
            try { return await attempt(fingerprint); } catch (error) {
                const pending = reserveConfirmation(error);
                if (!pending) throw error;
                const message = pending.changes.map((row) => `${row.name}：目標額 ${formatCurrency(row.target_before, currency)} → ${formatCurrency(row.target_after, currency)}、月額 ${formatCurrency(row.monthly_before, currency)} → ${formatCurrency(row.monthly_after, currency)}`).join('\n');
                if (!(await confirm(message, '変更して保存', '取り置きの変更'))) return userCancelled;
                fingerprint = pending.fingerprint;
            }
        }
    }, message, done);
    const rows = resource.data?.filter((row) => row.kind === TAB_KIND[tab]) ?? [];
    return <section className="space-y-4">
        <button type="button" disabled={disabled} onClick={() => setEditor({ entry: null })} className={buttonClass}>新規作成</button>
        <Feedback loading={resource.loading || lookups.loading} error={mutation.error || resource.error || lookups.error} message={mutation.message} />
        {editor && lookups.data && <AutoTransactionEditor entry={editor.entry} kind={TAB_KIND[tab]} currency={currency} accounts={lookups.data.accounts} busy={mutation.busy} error={mutation.error} onSave={save} onDelete={editor.entry ? () => void remove() : undefined} onClose={() => setEditor(null)} />}
        {product && lookups.data && <Overlay title={`${product.name}を編集`} busy={mutation.busy} onClose={() => setProduct(null)}><Feedback error={mutation.error} /><ProductEditor product={product} assets currency={currency} lookups={lookups.data} busy={mutation.busy} onSave={saveProduct} onCancel={() => setProduct(null)} onDelete={() => { void (async () => { if (await confirm(`「${product.name}」を削除しますか？`, '削除する')) saveProduct((fingerprint) => deleteProduct(product.id, fingerprint), '削除しました。'); })(); }} /></Overlay>}
        <DataTable columns={['名称', '繰り返し・次回', '金額', '口座', '予算']}>
            {rows.map((row) => <EditableRow key={row.id} disabled={disabled} onEdit={() => setEditor({ entry: row })}>
                <RowTitle name={row.name} disabled={disabled} onEdit={() => setEditor({ entry: row })}>{row.name}{!row.is_active && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">無効</span>}</RowTitle>
                <td className="px-5 py-3">{scheduleLabel(row)}<p className="text-xs text-[var(--studio-text-muted)]">次回 {row.next_due_date ?? '—'}</p></td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.amount, row.currency)}</td>
                <td className="px-5 py-3">{row.source_account_name ?? '—'} → {row.destination_account_name ?? '—'}<p className="text-xs text-[var(--studio-text-muted)]">予算口座：{row.budget_account_name ?? '自動'}</p></td>
                <td className="px-5 py-3">{row.budget_active ? '反映する' : '反映しない'}</td>
            </EditableRow>)}
            {!rows.length && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">自動取引はありません。</td></tr>}
        </DataTable>
        {tab === 'index' && <><h3 className="pt-4 text-sm font-semibold">固定資産の減価</h3><Feedback loading={depreciation.loading || products.loading} error={depreciation.error || products.error} />
            <DataTable columns={['名称', '方法・間隔', '次回の期と額', '帳簿価額', '自動で記帳']}>
                {depreciation.data?.map((row) => {
                    const item = products.data?.find((p) => p.id === row.product_id);
                    const open = () => { if (item) setProduct(item); };
                    return <EditableRow key={row.product_id} disabled={disabled || !item} onEdit={open}>
                        <RowTitle name={row.name} disabled={disabled || !item} onEdit={open}>{row.name}</RowTitle>
                        <td className="px-5 py-3">{row.method === 'straight_line' ? '定額法' : '定率法'}・{row.interval === 'monthly' ? '毎月' : '毎年'}</td>
                        <td className="px-5 py-3">{row.next_period ? `${row.next_period} ${formatCurrency(row.next_amount, row.currency)}` : '—'}</td>
                        <td className="px-5 py-3 tabular-nums">{formatCurrency(row.book_value, row.currency)}</td>
                        <td className="px-5 py-3">{row.auto_depreciation ? 'オン' : 'オフ'}</td>
                    </EditableRow>;
                })}
                {!depreciation.data?.length && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">固定資産の減価はありません。</td></tr>}
            </DataTable></>}
    </section>;
}

export default function AutoTransactions({ tab = 'index' }: { tab?: Tab }) {
    const { clientId, currentClient } = useClient();
    return <AutoTransactionsForClient key={`${clientId}:${tab}`} tab={tab} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
