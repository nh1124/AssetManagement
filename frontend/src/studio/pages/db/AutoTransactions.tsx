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
import { tr } from '../../i18n';

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
    const save = (form: AutoTransactionInput) => void mutation.run(() => editor?.entry ? updateAutoTransaction(editor.entry.id, form) : createAutoTransaction(form), tr('保存しました。', 'Saved.'), done);
    const remove = async () => {
        if (!editor?.entry || !(await confirm(tr(`「${editor.entry.name}」を削除しますか？`, `Delete “${editor.entry.name}”?`), tr('削除する', 'Delete')))) return;
        void mutation.run(() => deleteAutoTransaction(editor.entry!.id), tr('削除しました。', 'Deleted.'), done);
    };
    const saveProduct = (attempt: (fingerprint?: string) => Promise<unknown>, message = tr('保存しました。', 'Saved.')) => void mutation.run(async () => {
        let fingerprint: string | undefined;
        for (;;) {
            try { return await attempt(fingerprint); } catch (error) {
                const pending = reserveConfirmation(error);
                if (!pending) throw error;
                const message = pending.changes.map((row) => tr(`${row.name}：目標額 ${formatCurrency(row.target_before, currency)} → ${formatCurrency(row.target_after, currency)}、月額 ${formatCurrency(row.monthly_before, currency)} → ${formatCurrency(row.monthly_after, currency)}`, `${row.name}: target ${formatCurrency(row.target_before, currency)} → ${formatCurrency(row.target_after, currency)}, monthly ${formatCurrency(row.monthly_before, currency)} → ${formatCurrency(row.monthly_after, currency)}`)).join('\n');
                if (!(await confirm(message, tr('変更して保存', 'Change and save'), tr('取り置きの変更', 'Earmark changes')))) return userCancelled;
                fingerprint = pending.fingerprint;
            }
        }
    }, message, done);
    const rows = resource.data?.filter((row) => row.kind === TAB_KIND[tab]) ?? [];
    return <section className="space-y-4">
        <button type="button" disabled={disabled} onClick={() => setEditor({ entry: null })} className={buttonClass}>{tr('新規作成', 'New')}</button>
        <Feedback loading={resource.loading || lookups.loading} error={mutation.error || resource.error || lookups.error} message={mutation.message} />
        {editor && lookups.data && <AutoTransactionEditor entry={editor.entry} kind={TAB_KIND[tab]} currency={currency} accounts={lookups.data.accounts} busy={mutation.busy} error={mutation.error} onSave={save} onDelete={editor.entry ? () => void remove() : undefined} onClose={() => setEditor(null)} />}
        {product && lookups.data && <Overlay title={tr(`${product.name}を編集`, `Edit ${product.name}`)} busy={mutation.busy} onClose={() => setProduct(null)}><Feedback error={mutation.error} /><ProductEditor product={product} assets currency={currency} lookups={lookups.data} busy={mutation.busy} onSave={saveProduct} onCancel={() => setProduct(null)} onDelete={() => { void (async () => { if (await confirm(tr(`「${product.name}」を削除しますか？`, `Delete “${product.name}”?`), tr('削除する', 'Delete'))) saveProduct((fingerprint) => deleteProduct(product.id, fingerprint), tr('削除しました。', 'Deleted.')); })(); }} /></Overlay>}
        <DataTable columns={[tr('名称', 'Name'), tr('繰り返し・次回', 'Repeats / next'), tr('金額', 'Amount'), tr('口座', 'Accounts'), tr('予算', 'Budget')]}>
            {rows.map((row) => <EditableRow key={row.id} disabled={disabled} onEdit={() => setEditor({ entry: row })}>
                <RowTitle name={row.name} disabled={disabled} onEdit={() => setEditor({ entry: row })}>{row.name}{!row.is_active && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">{tr('無効', 'Inactive')}</span>}</RowTitle>
                <td className="px-5 py-3">{scheduleLabel(row)}<p className="text-xs text-[var(--studio-text-muted)]">{tr('次回', 'Next')} {row.next_due_date ?? '—'}</p></td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.amount, row.currency)}</td>
                <td className="px-5 py-3">{row.source_account_name ?? '—'} → {row.destination_account_name ?? '—'}<p className="text-xs text-[var(--studio-text-muted)]">{tr('予算口座：', 'Budget account: ')}{row.budget_account_name ?? tr('自動', 'automatic')}</p></td>
                <td className="px-5 py-3">{row.budget_active ? tr('反映する', 'Included') : tr('反映しない', 'Not included')}</td>
            </EditableRow>)}
            {!rows.length && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('自動取引はありません。', 'No automatic transactions.')}</td></tr>}
        </DataTable>
        {tab === 'index' && <><h3 className="pt-4 text-sm font-semibold">{tr('固定資産の減価', 'Fixed asset depreciation')}</h3><Feedback loading={depreciation.loading || products.loading} error={depreciation.error || products.error} />
            <DataTable columns={[tr('名称', 'Name'), tr('方法・間隔', 'Method / interval'), tr('次回の期と額', 'Next period and amount'), tr('帳簿価額', 'Book value'), tr('自動で記帳', 'Automatic posting')]}>
                {depreciation.data?.map((row) => {
                    const item = products.data?.find((p) => p.id === row.product_id);
                    const open = () => { if (item) setProduct(item); };
                    return <EditableRow key={row.product_id} disabled={disabled || !item} onEdit={open}>
                        <RowTitle name={row.name} disabled={disabled || !item} onEdit={open}>{row.name}</RowTitle>
                        <td className="px-5 py-3">{row.method === 'straight_line' ? tr('定額法', 'Straight line') : tr('定率法', 'Declining balance')}{tr('・', ', ')}{row.interval === 'monthly' ? tr('毎月', 'monthly') : tr('毎年', 'yearly')}</td>
                        <td className="px-5 py-3">{row.next_period ? `${row.next_period} ${formatCurrency(row.next_amount, row.currency)}` : '—'}</td>
                        <td className="px-5 py-3 tabular-nums">{formatCurrency(row.book_value, row.currency)}</td>
                        <td className="px-5 py-3">{row.auto_depreciation ? tr('オン', 'On') : tr('オフ', 'Off')}</td>
                    </EditableRow>;
                })}
                {!depreciation.data?.length && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('固定資産の減価はありません。', 'No fixed asset depreciation.')}</td></tr>}
            </DataTable></>}
    </section>;
}

export default function AutoTransactions({ tab = 'index' }: { tab?: Tab }) {
    const { clientId, currentClient } = useClient();
    return <AutoTransactionsForClient key={`${clientId}:${tab}`} tab={tab} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
