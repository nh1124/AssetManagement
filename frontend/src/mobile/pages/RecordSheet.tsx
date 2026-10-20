import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ExternalLink } from 'lucide-react';
import { createTransaction, deleteTransaction, getAccounts, getTransaction, updateTransaction } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { Account, Transaction, TransactionLeg, TransactionLegRead } from '../../types';
import { getCurrencySymbol } from '../../utils/currency';
import { useConfirm } from '../../studio/components/useConfirm';
import { clientToday, useTimezone } from '../../studio/datetime';
import { assetErrorMessage, useResource } from '../../studio/useResource';
import Sheet from '../components/Sheet';
import { useSnack } from '../components/snack';
import { dangerButton, Field, fieldClass, focusRing, primaryButton, Segmented } from '../components/ui';

type Kind = 'expense' | 'income' | 'transfer';
type AccountType = Account['account_type'];
const KIND_OPTIONS: Array<{ value: Kind; label: string }> = [{ value: 'expense', label: '支出' }, { value: 'income', label: '収入' }, { value: 'transfer', label: '振替' }];
// Which accounts each side of a kind may name: 支出 debits an expense from money, 収入 credits income into an asset.
const SUBJECT_TYPES: Record<Kind, AccountType[]> = { expense: ['expense'], income: ['income'], transfer: [] };
const FROM_TYPES: Record<Kind, AccountType[]> = { expense: ['asset', 'liability'], income: [], transfer: ['asset', 'liability'] };
const TO_TYPES: Record<Kind, AccountType[]> = { expense: [], income: ['asset'], transfer: ['asset', 'liability'] };
const RECENT_KEY = 'mobile.record.recent';
const FROM_KEY = 'mobile.record.from';
const SHOWN_SUBJECTS = 8;

function stored<T>(key: string, fallback: T): T {
    try {
        const raw = window.localStorage.getItem(key);
        return raw ? JSON.parse(raw) as T : fallback;
    } catch {
        return fallback;
    }
}

function store(key: string, value: unknown) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* a private window keeps nothing */ }
}

/** A plain two-leg entry read back into the form; anything else (memos, earmarks, a write-down, more legs) stays on the studio. */
function readSimple(transaction: Transaction, accounts: Account[]): { kind: Kind; subject: number | null; from: number | null; to: number | null } | null {
    const legs = (transaction.legs ?? []) as TransactionLegRead[];
    if (legs.length !== 2 || transaction.depreciation || legs.some((leg) => leg.capsule_id || leg.memo)) return null;
    const debit = legs.find((leg) => (leg.debit ?? 0) > 0);
    const credit = legs.find((leg) => (leg.credit ?? 0) > 0);
    if (!debit || !credit) return null;
    const type = (leg: TransactionLegRead) => leg.account_type ?? accounts.find((account) => account.id === leg.account_id)?.account_type;
    if (type(debit) === 'expense') return { kind: 'expense', subject: debit.account_id, from: credit.account_id, to: null };
    if (type(credit) === 'income') return { kind: 'income', subject: credit.account_id, from: null, to: debit.account_id };
    return { kind: 'transfer', subject: null, from: credit.account_id, to: debit.account_id };
}

/** Record a 支出, 収入 or 振替 in a few taps; an existing two-leg record opens to change or delete it. */
export default function RecordSheet({ transaction, onClose, onSaved }: { transaction: Transaction | null; onClose: () => void; onSaved: () => void }) {
    const { currentClient } = useClient();
    // An existing record keeps its own currency; a new one is in the client's.
    const currency = transaction?.currency || currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const confirm = useConfirm();
    const snack = useSnack();
    const load = useCallback(async () => {
        const [accounts, full] = await Promise.all([getAccounts(undefined, true), transaction ? getTransaction(transaction.id) : Promise.resolve(null)]);
        return { accounts, full };
    }, [transaction]);
    const resource = useResource(load);
    const accounts = useMemo(() => resource.data?.accounts ?? [], [resource.data]);
    const [kind, setKind] = useState<Kind>('expense');
    const [amount, setAmount] = useState(transaction ? String(transaction.amount) : '');
    const [subject, setSubject] = useState<number | null>(null);
    const [from, setFrom] = useState<number | null>(stored<number | null>(FROM_KEY, null));
    const [to, setTo] = useState<number | null>(null);
    const [date, setDate] = useState(transaction?.date ?? clientToday(timezone));
    const [description, setDescription] = useState(transaction?.description ?? '');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [simple, setSimple] = useState(true);
    const [allSubjects, setAllSubjects] = useState(false);
    const [touched, setTouched] = useState(false);
    const amountInput = useRef<HTMLInputElement>(null);
    const read = useRef(false);
    useEffect(() => {
        if (!resource.data || read.current) return;
        read.current = true;
        if (!resource.data.full) {
            amountInput.current?.focus();
            return;
        }
        const parsed = readSimple(resource.data.full, resource.data.accounts);
        if (!parsed) { setSimple(false); return; }
        setKind(parsed.kind);
        setSubject(parsed.subject);
        setFrom(parsed.from);
        setTo(parsed.to);
    }, [resource.data]);
    const typeOf = (id: number | null) => accounts.find((account) => account.id === id)?.account_type;
    const allowed = (id: number | null, types: AccountType[]) => id !== null && types.includes(typeOf(id) as AccountType);
    const recent = stored<number[]>(RECENT_KEY, []);
    const subjects = accounts.filter((account) => SUBJECT_TYPES[kind].includes(account.account_type))
        .sort((a, b) => {
            const rank = (id: number) => { const index = recent.indexOf(id); return index === -1 ? Infinity : index; };
            return rank(a.id) - rank(b.id) || a.name.localeCompare(b.name, 'ja');
        });
    const shownSubjects = allSubjects ? subjects : subjects.slice(0, SHOWN_SUBJECTS).concat(subjects.slice(SHOWN_SUBJECTS).filter((account) => account.id === subject));
    const choices = (types: AccountType[]) => accounts.filter((account) => types.includes(account.account_type));
    const value = Number(amount);
    const chooseKind = (next: Kind) => {
        setKind(next);
        setError('');
        setTouched(true);
        // Keep only picks the new kind can use: a hidden liability must never become an income's destination.
        setSubject((id) => allowed(id, SUBJECT_TYPES[next]) ? id : null);
        setFrom((id) => allowed(id, FROM_TYPES[next]) ? id : null);
        setTo((id) => allowed(id, TO_TYPES[next]) ? id : null);
    };
    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (busy) return;
        const missing = !(Number.isFinite(value) && value > 0) ? '金額を入力してください。'
            : kind !== 'transfer' && !allowed(subject, SUBJECT_TYPES[kind]) ? (kind === 'expense' ? '費目を選んでください。' : '収入の種類を選んでください。')
            : kind !== 'income' && !allowed(from, FROM_TYPES[kind]) ? (kind === 'expense' ? '支払った口座を選んでください。' : '振替元を選んでください。')
            : kind !== 'expense' && !allowed(to, TO_TYPES[kind]) ? (kind === 'income' ? '入金した口座を選んでください。' : '振替先を選んでください。')
            : kind === 'transfer' && from === to ? '振替元と別の振替先を選んでください。'
            : !date ? '日付を入力してください。' : '';
        if (missing) { setError(missing); return; }
        const legs: TransactionLeg[] = kind === 'expense' ? [{ account_id: subject as number, debit: value }, { account_id: from as number, credit: value }]
            : kind === 'income' ? [{ account_id: to as number, debit: value }, { account_id: subject as number, credit: value }]
            : [{ account_id: to as number, debit: value }, { account_id: from as number, credit: value }];
        setBusy(true);
        setError('');
        try {
            const payload = { date, amount: value, description: description.trim(), currency, legs };
            const result = transaction ? await updateTransaction(transaction.id, payload) : await createTransaction(payload);
            if (subject !== null) store(RECENT_KEY, [subject, ...recent.filter((id) => id !== subject)].slice(0, 12));
            if (kind === 'expense' && from !== null) store(FROM_KEY, from);
            snack(`${transaction ? '記録を更新しました' : '記録しました'}${result.closed_period ? `（${result.closed_period} は締め済みです）` : ''}`);
            onSaved();
        } catch (failure) {
            setError(assetErrorMessage(failure));
        } finally {
            setBusy(false);
        }
    };
    const remove = async () => {
        if (!transaction || busy) return;
        if (!(await confirm(`${transaction.date}「${transaction.description || '内容なし'}」を削除します。削除は取り消せません。`, '削除する'))) return;
        setBusy(true);
        try {
            await deleteTransaction(transaction.id);
            snack('記録を削除しました');
            onSaved();
        } catch (failure) {
            setError(assetErrorMessage(failure));
            setBusy(false);
        }
    };
    const dismiss = async () => {
        if (busy) return;
        // Typed input is not thrown away by a stray tap on the backdrop.
        if (touched && simple && !(await confirm('入力した内容は保存されません。閉じますか？', '閉じる', '入力の破棄'))) return;
        onClose();
    };
    const edit = <T,>(setter: (value: T) => void) => (value: T) => { setter(value); setTouched(true); };
    const accountSelect = (label: string, selected: number | null, options: Account[], onChange: (id: number | null) => void) => <Field label={label}>
        <select value={selected ?? ''} onChange={(event) => edit(onChange)(event.target.value ? Number(event.target.value) : null)} className={fieldClass}>
            <option value="">選んでください</option>
            {options.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
        </select>
    </Field>;
    const form = 'mobile-record-form';
    return <Sheet title={transaction ? '記録を編集' : '取引を記録'} onClose={() => void dismiss()} busy={busy} tall
        footer={simple && resource.data ? <div className="flex gap-3">
            {transaction && <button type="button" onClick={() => void remove()} disabled={busy} className={dangerButton}>削除</button>}
            <button type="submit" form={form} disabled={busy} className={`${primaryButton} flex-1`}>{busy ? '保存しています…' : transaction ? '保存する' : '記録する'}</button>
        </div> : undefined}>
        {resource.error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-[var(--studio-danger)]">{resource.error}</p>}
        {!resource.data && !resource.error && <div className="h-40 animate-pulse rounded-2xl bg-[var(--studio-surface)]" />}
        {resource.data && !simple && <div className="space-y-3 rounded-2xl bg-[var(--studio-surface)] p-4 text-sm">
            <p>この記録は、内訳が複数ある・メモや取り置き・減価償却が付いている取引です。PC版の家計簿で編集してください。</p>
            <a href="/studio/ledger" className={`inline-flex min-h-11 items-center gap-1 font-medium text-[var(--studio-accent)] ${focusRing}`}>PC版で開く<ExternalLink size={14} aria-hidden /></a>
        </div>}
        {resource.data && simple && <form id={form} onSubmit={(event) => void submit(event)} className="space-y-5">
            <Segmented label="記録の種類" value={kind} options={KIND_OPTIONS} onChange={chooseKind} />
            <label className="block rounded-2xl bg-[var(--studio-surface)] px-4 py-3 shadow-[var(--mobile-shadow)]">
                <span className="text-xs font-medium text-[var(--studio-text-muted)]">金額{currency !== (currentClient?.general_settings?.currency || 'JPY') ? `（${currency}）` : ''}</span>
                <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-semibold text-[var(--studio-text-muted)]">{getCurrencySymbol(currency)}</span>
                    <input ref={amountInput} inputMode="decimal" value={amount} placeholder="0" aria-label="金額"
                        onChange={(event) => edit(setAmount)(event.target.value.replace(/[^\d.]/g, ''))}
                        className="w-full bg-transparent text-4xl font-bold tabular-nums tracking-tight focus:outline-none" />
                </div>
            </label>
            {kind !== 'transfer' && <fieldset>
                <legend className="mb-2 text-xs font-medium text-[var(--studio-text-muted)]">{kind === 'expense' ? '費目' : '収入の種類'}</legend>
                {subjects.length ? <div className="flex flex-wrap gap-2">
                    {shownSubjects.map((account) => <button key={account.id} type="button" aria-pressed={subject === account.id} onClick={() => edit(setSubject)(account.id)}
                        className={`min-h-11 rounded-full border px-4 text-sm ${focusRing} ${subject === account.id ? 'border-[var(--studio-accent)] bg-[var(--studio-accent)] text-white' : 'border-[var(--studio-border)] bg-[var(--studio-surface)]'}`}>{account.name}</button>)}
                    {subjects.length > SHOWN_SUBJECTS && <button type="button" onClick={() => setAllSubjects((shown) => !shown)}
                        className={`min-h-11 rounded-full px-3 text-sm font-medium text-[var(--studio-accent)] ${focusRing}`}>{allSubjects ? '少なく表示' : `ほか ${subjects.length - SHOWN_SUBJECTS}件`}</button>}
                </div> : <p className="text-sm text-[var(--studio-text-muted)]">{kind === 'expense' ? '費用' : '収益'}の科目がありません。PC版のデータベースで追加してください。</p>}
            </fieldset>}
            {kind === 'expense' && accountSelect('支払った口座', from, choices(FROM_TYPES.expense), setFrom)}
            {kind === 'income' && accountSelect('入金した口座', to, choices(TO_TYPES.income), setTo)}
            {kind === 'transfer' && <div className="grid gap-4">
                {accountSelect('振替元', from, choices(FROM_TYPES.transfer), setFrom)}
                {accountSelect('振替先', to, choices(TO_TYPES.transfer).filter((account) => account.id !== from), setTo)}
            </div>}
            <div className="grid grid-cols-2 gap-3">
                <Field label="日付"><input type="date" required value={date} onChange={(event) => edit(setDate)(event.target.value)} className={fieldClass} /></Field>
                <Field label="内容"><input value={description} placeholder="任意" onChange={(event) => edit(setDescription)(event.target.value)} className={fieldClass} /></Field>
            </div>
            {error && <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-[var(--studio-danger)]">{error}</p>}
        </form>}
    </Sheet>;
}
