import { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { compareStatement, postReconciliationAdjustment } from '../../../api/reconciliation';
import { getCapsules } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { ReconciliationComparison, Transaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { Choice, DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation, type DatabaseAccount } from '../db/forms';
import { tr } from '../../i18n';

function ReconciliationForClient({ account, accounts, disabled, onPosted }: {
    account: DatabaseAccount; accounts: DatabaseAccount[]; disabled: boolean; onPosted: () => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const capsules = useResource(getCapsules);
    const mutation = useMutation();
    const accountId = account.id;
    const [currency, setCurrency] = useState(currentClient?.general_settings?.currency || 'JPY');
    const [date, setDate] = useState(() => clientToday(timezone));
    const [statement, setStatement] = useState('');
    const [comparison, setComparison] = useState<ReconciliationComparison | null>(null);
    const [counterId, setCounterId] = useState<number | null>(null);
    const [capsuleId, setCapsuleId] = useState<number | null>(null);
    const [note, setNote] = useState('');
    const [posted, setPosted] = useState<Transaction | null>(null);
    const identified = currentClient?.id === clientId;
    const locked = disabled || mutation.busy || !identified;
    const invalidate = () => { setComparison(null); setPosted(null); };
    const compare = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (locked || !statement.trim() || !Number.isFinite(Number(statement))) return;
        setComparison(null);
        setPosted(null);
        let result: ReconciliationComparison | null = null;
        void mutation.run(async () => { result = await compareStatement(accountId, date, statement, currency); }, '', () => setComparison(result));
    };
    const post = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (locked || !comparison || comparison.difference_minor === 0 || counterId === null || counterId === comparison.account.id) return;
        const factor = ['JPY', 'KRW'].includes(comparison.currency) ? 1 : 100;
        const direction = comparison.difference_minor > 0 ? tr('増やす（借方）', 'increase (debit)') : tr('減らす（貸方）', 'decrease (credit)');
        const counter = accounts.find((row) => row.id === counterId);
        const capsule = capsules.data?.find((row) => row.id === capsuleId);
        if (!(await confirm(tr(
            `「${currentClient?.name}」の${formatDate(comparison.as_of, timezone)}の口座「${comparison.account.name}」を ${formatCurrency(Math.abs(comparison.difference_minor) / factor, comparison.currency)}（${comparison.currency}）${direction}調整を記帳しますか？\n相手科目：${counter?.name ?? `#${counterId}`}\n取り置き：${capsule?.name ?? '指定しない'}`,
            `Record an adjustment to ${direction} “${comparison.account.name}” by ${formatCurrency(Math.abs(comparison.difference_minor) / factor, comparison.currency)} (${comparison.currency}) as of ${formatDate(comparison.as_of, timezone)} for “${currentClient?.name}”?\nCounter account: ${counter?.name ?? `#${counterId}`}\nEarmark: ${capsule?.name ?? 'none'}`,
        ), tr('記帳する', 'Record')))) return;
        let transaction: Transaction | null = null;
        void mutation.run(async () => {
            transaction = await postReconciliationAdjustment(comparison.account.id, {
                as_of: comparison.as_of, statement, currency: comparison.currency,
                counter_account_id: counterId, capsule_id: capsuleId ?? undefined,
                note: note.trim() || undefined, expected_ledger_minor: comparison.ledger_minor,
            });
        }, tr('調整仕訳を記帳しました。', 'Adjustment recorded.'), () => {
            // A committed adjustment cannot be retried if refreshing fails.
            setPosted(transaction);
            setComparison(null);
            onPosted();
        });
    };
    const factor = comparison && ['JPY', 'KRW'].includes(comparison.currency) ? 1 : 100;
    return <section className="space-y-4">
        <form onSubmit={compare} className="space-y-3">
            <fieldset disabled={locked} className="grid gap-3 md:grid-cols-2">
                <Field label={tr('基準日', 'As of')}><input required type="date" value={date} onChange={(event) => { setDate(event.target.value); invalidate(); }} className={inputClass} /></Field>
                <Field label={tr('通貨', 'Currency')} help={tr('選んだ通貨の残高だけを照合します。他の通貨は合算しません。', 'Only the balance in the chosen currency is compared. Other currencies are not added in.')}><select value={currency} onChange={(event) => { setCurrency(event.target.value); invalidate(); }} className={inputClass}>{['JPY', 'USD', 'EUR'].map((code) => <option key={code} value={code}>{code}</option>)}</select></Field>
                <Field label={tr(`実残高（${currency}）`, `Statement balance (${currency})`)} help={tr('帳簿残高は借方 − 貸方です。負債・収入など貸方に残る残高は、マイナスで入力してください。', 'The ledger balance is debits minus credits. Enter credit balances, such as liabilities and income, as negative numbers.')}><input required type="number" step={['JPY', 'KRW'].includes(currency) ? '1' : '0.01'} value={statement} onChange={(event) => { setStatement(event.target.value); invalidate(); }} className={inputClass} /></Field>
                <button type="submit" disabled={!statement.trim()} className={buttonClass}>{tr('照合する', 'Compare')}</button>
            </fieldset>
        </form>
        <Feedback error={mutation.error} message={mutation.message} />
        {posted && <p role="status" className="text-sm">{tr(`調整取引 #${posted.id}：${formatCurrency(posted.amount, posted.currency)}（${posted.currency}）。もう一度照合すると更新後の残高を確認できます。`, `Adjustment #${posted.id}: ${formatCurrency(posted.amount, posted.currency)} (${posted.currency}). Compare again to see the updated balance.`)}</p>}
        {comparison && <div className="space-y-4">
            <p className="text-xs text-[var(--studio-text-muted)]">{comparison.account.name} / {formatDate(comparison.as_of, timezone)} / {comparison.currency}</p>
            <dl className="grid gap-3 sm:grid-cols-3">{[
                [tr('帳簿残高', 'Ledger balance'), comparison.ledger_minor], [tr('実残高', 'Statement balance'), comparison.statement_minor], [tr('差額', 'Difference'), comparison.difference_minor],
            ].map(([label, value]) => <div key={label}><dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt><dd className="mt-1 font-semibold tabular-nums">{formatCurrency(Number(value) / factor, comparison.currency)}</dd></div>)}</dl>
            <p className="text-sm">{tr('この口座の取り置き（基準日までの確保額）', 'Earmarks in this account (set aside up to the as-of date)')}</p>
            <DataTable columns={[tr('取り置き', 'Earmark'), tr(`確保額（${comparison.currency}）`, `Set aside (${comparison.currency})`)]}>
                {comparison.capsule_claims.length ? comparison.capsule_claims.map((row) => <tr key={row.capsule_id}><th scope="row" className="px-5 py-3 font-normal">{row.capsule_name}</th><td className="px-5 py-3 tabular-nums">{formatCurrency(row.claimed_minor / factor, comparison.currency)}</td></tr>) : <tr><td colSpan={2} className="px-5 py-3 text-[var(--studio-text-muted)]">{tr('この口座・通貨の取り置きはありません。', 'No earmarks for this account and currency.')}</td></tr>}
            </DataTable>
            {comparison.difference_minor === 0 ? <p role="status" className="text-sm text-[var(--studio-positive)]">{tr('差額はありません。調整は不要です。', 'No difference. No adjustment is needed.')}</p> : <form id={formId} onSubmit={post} className="space-y-3">
                <fieldset disabled={locked} className="grid gap-3 md:grid-cols-2">
                    <Choice label={tr('相手科目', 'Counter account')} value={counterId} options={accounts.filter((row) => row.id !== comparison.account.id)} required onChange={setCounterId} />
                    <div><fieldset disabled={capsules.loading || Boolean(capsules.error)}><Choice label={tr('調整を帰属させる取り置き（任意）', 'Earmark for the adjustment (optional)')} help={tr('取り置きを指定すると、照合する口座の確保額も差額だけ変わります。指定しなければ、取り置きの確保額は変わりません。', 'With an earmark, the amount set aside in this account changes by the difference too. Without one, set-aside amounts do not change.')} value={capsuleId} options={capsules.data ?? []} onChange={setCapsuleId} /></fieldset></div>
                    <Field label={tr('メモ（任意）', 'Note (optional)')}><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field>
                    <OverlayFooter><button type="submit" form={formId} disabled={locked || counterId === null || counterId === comparison.account.id} className={primaryClass}>{mutation.busy ? tr('記帳中…', 'Recording…') : tr('調整を記帳', 'Record adjustment')}</button></OverlayFooter>
                </fieldset>
                <Feedback loading={capsules.loading} error={capsules.error} />
                {capsules.error && <button type="button" disabled={mutation.busy} onClick={capsules.reload} className={buttonClass}>{tr('取り置きを再取得', 'Reload earmarks')}</button>}
            </form>}
        </div>}
    </section>;
}

export default function Reconciliation(props: { account: DatabaseAccount; accounts: DatabaseAccount[]; disabled: boolean; onPosted: () => void }) {
    const { clientId, currentClient } = useClient();
    return <ReconciliationForClient key={`${clientId}:${props.account.id}:${currentClient?.general_settings?.currency}`} {...props} />;
}
