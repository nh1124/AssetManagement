import Overlay, { OverlayFooter } from '../../components/Overlay';
import DrawdownClaim from '../../components/DrawdownClaim';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { getAccounts, getCapsuleDrawdowns, recordCapsuleDrawdown } from '../../../api';
import type { Capsule, CapsuleDrawdownKind } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, today, useMutation, type DatabaseAccount } from '../db/forms';
import { tr } from '../../i18n';

const loadDestinations = async (): Promise<DatabaseAccount[]> => (await getAccounts() as DatabaseAccount[])
    .filter((account) => ['asset', 'expense'].includes(account.account_type) && account.is_active);
const kindLabel = (kind: CapsuleDrawdownKind) => kind === 'as_intended' ? tr('意図どおり使った', 'Used as intended') : tr('他に回した', 'Used for something else');

function DrawdownForm({ capsule, currency, onRecorded }: {
    capsule: Capsule; currency: string; onRecorded: (message: string) => void;
}) {
    const formId = useId();
    const accounts = useResource(loadDestinations);
    const mutation = useMutation();
    const [amount, setAmount] = useState('');
    const [fromAccountId, setFromAccountId] = useState('');
    const [toAccountId, setToAccountId] = useState('');
    const [kind, setKind] = useState<CapsuleDrawdownKind>('as_intended');
    const [date, setDate] = useState(today);
    const [description, setDescription] = useState('');
    const source = capsule.funding_sources?.find((row) => String(row.account_id) === fromAccountId);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        let confirmation = '';
        void mutation.run(async () => {
            const result = await recordCapsuleDrawdown(capsule.id, {
                amount: Number(amount), from_account_id: Number(fromAccountId),
                to_account_id: Number(toAccountId), kind, date, description,
            });
            confirmation = tr(`${formatCurrency(result.drawdown.amount, result.drawdown.currency)}を取り崩しました（${kindLabel(result.drawdown.kind)}）。取引 #${result.transaction.id}`, `Drew down ${formatCurrency(result.drawdown.amount, result.drawdown.currency)} (${kindLabel(result.drawdown.kind).toLowerCase()}). Transaction #${result.transaction.id}`);
        }, '', () => onRecorded(confirmation));
    };
    return <form id={formId} onSubmit={submit} className="space-y-3">
        <Feedback loading={accounts.loading} error={mutation.error || accounts.error} />
        <fieldset disabled={mutation.busy || accounts.loading || Boolean(accounts.error)} className="grid gap-3 md:grid-cols-2">
            <div><Field label={tr(`金額（${currency}）`, `Amount (${currency})`)}><input required type="number" min="0.01" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
                {source && <DrawdownClaim key={`${capsule.id}:${source.account_id}:${currency}`} accountId={source.account_id} accountName={source.account_name ?? tr(`口座 #${source.account_id}`, `Account #${source.account_id}`)} capsuleId={capsule.id} currency={currency} />}
            </div>
            <Field label={tr('引き出す口座', 'Take from')}><select required value={fromAccountId} onChange={(event) => setFromAccountId(event.target.value)} className={inputClass}>
                <option value="">{tr('選択してください', 'Choose…')}</option>
                {capsule.funding_sources?.map((source) => <option key={source.id} value={source.account_id}>{source.account_name ?? `#${source.account_id}`}</option>)}
            </select></Field>
            <Field label={tr('使い道の口座', 'Spent on')}><select required value={toAccountId} onChange={(event) => setToAccountId(event.target.value)} className={inputClass}>
                <option value="">{tr('選択してください', 'Choose…')}</option>
                {accounts.data?.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </select></Field>
            <Field label={tr('区分', 'Kind')}><select value={kind} onChange={(event) => setKind(event.target.value as CapsuleDrawdownKind)} className={inputClass}>
                <option value="as_intended">{tr('意図どおり使った', 'Used as intended')}</option><option value="diverted">{tr('他に回した', 'Used for something else')}</option>
            </select></Field>
            <Field label={tr('日付', 'Date')}><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('内容', 'Description')}><input type="text" value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></Field>
            <OverlayFooter><button type="submit" form={formId} disabled={mutation.busy || accounts.loading || Boolean(accounts.error) || !capsule.funding_sources?.length} className={primaryClass}>{mutation.busy ? tr('記録中…', 'Recording…') : tr('記録する', 'Record')}</button></OverlayFooter>
        </fieldset>
    </form>;
}

export default function Drawdowns({ capsule, currency, onRecorded }: { capsule: Capsule; currency: string; onRecorded: () => void }) {
    const load = useCallback(() => getCapsuleDrawdowns(capsule.id), [capsule.id]);
    const history = useResource(load);
    const [open, setOpen] = useState(false);
    const [message, setMessage] = useState('');
    return <div className="space-y-3">
        <Feedback message={message} loading={history.loading} error={history.error} />
        {open ? <Overlay title={tr(`「${capsule.name}」を取り崩す`, `Draw down “${capsule.name}”`)} onClose={() => setOpen(false)}><DrawdownForm capsule={capsule} currency={currency} onRecorded={(result) => {
            setOpen(false); setMessage(result); history.reload(); onRecorded();
        }} /></Overlay> : <button type="button" onClick={() => { setMessage(''); setOpen(true); }} disabled={!capsule.funding_sources?.length} className={buttonClass}>{tr('取り崩す', 'Draw down')}</button>}
        {history.data && <DataTable columns={[tr('日付', 'Date'), tr('金額', 'Amount'), tr('区分', 'Kind'), tr('内容', 'Description')]}>
            {history.data.length ? history.data.map((row) => <tr key={row.id}>
                <th scope="row" className="whitespace-nowrap px-5 py-3 font-normal">{row.date}</th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.amount, row.currency)}</td>
                <td className="px-5 py-3">{kindLabel(row.kind)}</td><td className="px-5 py-3">{row.description}</td>
            </tr>) : <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('取り崩しはありません。', 'No drawdowns.')}</td></tr>}
        </DataTable>}
    </div>;
}
