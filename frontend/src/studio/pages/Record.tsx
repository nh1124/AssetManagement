import { useEffect, useRef, useState, type FormEvent } from 'react';
import { isAxiosError } from 'axios';
import { contributeToCapsule, createTransaction, getAccounts, getCapsules, recordCapsuleDrawdown } from '../../api';
import { useClient } from '../../context/ClientContext';
import { getCurrencySymbol } from '../../utils/currency';
import type { Account, Capsule, CapsuleDrawdownKind, TransactionLeg } from '../../types';

// The API also returns item accounts, which the shared legacy type omits.
type RecordAccount = Omit<Account, 'account_type'> & {
    account_type: Account['account_type'] | 'item';
};
type AccountType = RecordAccount['account_type'];
type RecordKind = 'income' | 'expense' | 'transfer' | 'allocation' | 'purchase' | 'repayment';
interface SplitRow {
    accountId: string;
    amount: string;
    memo: string;
}

const KINDS: Array<{ value: RecordKind; label: string }> = [
    { value: 'income', label: '収入' },
    { value: 'expense', label: '支出' },
    { value: 'transfer', label: '口座振替' },
    { value: 'allocation', label: '用途確保' },
    { value: 'purchase', label: '物品購入' },
    { value: 'repayment', label: '元本返済' },
];

const ACCOUNT_FIELDS: Record<RecordKind, {
    debitLabel: string;
    debitTypes: AccountType[];
    creditLabel: string;
    creditTypes: AccountType[];
}> = {
    income: { debitLabel: '入金先口座', debitTypes: ['asset'], creditLabel: '収入科目', creditTypes: ['income'] },
    expense: { debitLabel: '費用科目', debitTypes: ['expense'], creditLabel: '支払元口座', creditTypes: ['asset', 'liability'] },
    transfer: { debitLabel: '振替先口座', debitTypes: ['asset'], creditLabel: '振替元口座', creditTypes: ['asset'] },
    allocation: { debitLabel: '', debitTypes: [], creditLabel: '資金元口座', creditTypes: ['asset'] },
    purchase: { debitLabel: '物品または費用', debitTypes: ['item', 'expense'], creditLabel: '支払元口座', creditTypes: ['asset', 'liability'] },
    repayment: { debitLabel: '返済する負債', debitTypes: ['liability'], creditLabel: '支払元口座', creditTypes: ['asset'] },
};

const inputClass = 'w-full rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] px-3 py-2 text-sm text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
const secondaryButtonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';

function today() {
    // UTC can still be yesterday when the user starts recording in the morning.
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

function errorMessage(error: unknown): string {
    if (isAxiosError<{ detail?: unknown; message?: string }>(error)) {
        const data = error.response?.data;
        if (typeof data?.detail === 'string') return data.detail;
        if (Array.isArray(data?.detail)) {
            const messages = data.detail.flatMap((entry: unknown) =>
                typeof entry === 'object' && entry !== null && 'msg' in entry && typeof entry.msg === 'string'
                    ? [entry.msg] : []);
            if (messages.length) return messages.join('、');
        }
        if (typeof data?.message === 'string') return data.message;
    }
    return error instanceof Error ? error.message : '記録できませんでした。もう一度お試しください。';
}

function AccountSelect({ label, value, accounts, onChange }: {
    label: string;
    value: string;
    accounts: RecordAccount[];
    onChange: (value: string) => void;
}) {
    return (
        <label className="block space-y-2 text-sm">
            <span className="text-[var(--studio-text-muted)]">{label}</span>
            <select required value={value} onChange={(event) => onChange(event.target.value)} className={inputClass}>
                <option value="">選択してください</option>
                {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </select>
        </label>
    );
}

function RecordForClient() {
    const { currentClient } = useClient();
    // Money is per-currency here and is never totalled across currencies, so
    // the entry takes the client's currency rather than assuming one.
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [accounts, setAccounts] = useState<RecordAccount[]>([]);
    const [capsules, setCapsules] = useState<Capsule[]>([]);
    const [accountsLoading, setAccountsLoading] = useState(true);
    const [capsulesLoading, setCapsulesLoading] = useState(true);
    const [accountsError, setAccountsError] = useState('');
    const [capsulesError, setCapsulesError] = useState('');
    const [kind, setKind] = useState<RecordKind>('expense');
    const [date, setDate] = useState(today);
    const [amount, setAmount] = useState('');
    const [description, setDescription] = useState('');
    const [debitAccountId, setDebitAccountId] = useState('');
    const [creditAccountId, setCreditAccountId] = useState('');
    const [capsuleId, setCapsuleId] = useState('');
    const [drawdownCapsuleId, setDrawdownCapsuleId] = useState('');
    const [drawdownKind, setDrawdownKind] = useState<CapsuleDrawdownKind>('as_intended');
    const [splitRows, setSplitRows] = useState<SplitRow[]>([]);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const submitInFlight = useRef(false);

    useEffect(() => {
        let stale = false;
        void getAccounts().then((data) => {
            if (!stale) setAccounts(data);
        }).catch((failure: unknown) => {
            if (!stale) setAccountsError(errorMessage(failure));
        }).finally(() => {
            if (!stale) setAccountsLoading(false);
        });
        // A capsule lookup failure must not block ordinary transaction recording.
        void getCapsules().then((data: Capsule[]) => {
            if (!stale) setCapsules(data);
        }).catch((failure: unknown) => {
            if (!stale) setCapsulesError(errorMessage(failure));
        }).finally(() => {
            if (!stale) setCapsulesLoading(false);
        });
        return () => { stale = true; };
    }, []);

    const fields = ACCOUNT_FIELDS[kind];
    const debitAccounts = accounts.filter((account) => fields.debitTypes.includes(account.account_type));
    const supportsDrawdown = kind === 'expense' || kind === 'purchase';
    const drawdownCapsule = supportsDrawdown ? capsules.find((capsule) => String(capsule.id) === drawdownCapsuleId) : undefined;
    const drawdownActive = supportsDrawdown && Boolean(drawdownCapsuleId);
    const creditAccounts = accounts.filter((account) => fields.creditTypes.includes(account.account_type)
        && (!drawdownActive || drawdownCapsule?.funding_sources?.some((source) => source.account_id === account.id)));
    const supportsSplit = supportsDrawdown && !drawdownActive;
    const splitActive = supportsSplit && splitRows.length > 0;
    const numericAmount = Number(amount);
    const splitTotal = splitRows.reduce((sum, row) => sum + (Number(row.amount) || 0), 0);
    const splitRemainder = (numericAmount || 0) - splitTotal;
    const splitBalanced = Math.abs(splitRemainder) < 0.01;
    const hasAccount = (options: RecordAccount[], id: string) => options.some((account) => String(account.id) === id);
    const validAmount = Number.isFinite(numericAmount) && numericAmount > 0;
    const validDebit = splitActive
        ? splitBalanced && splitRows.every((row) => hasAccount(debitAccounts, row.accountId) && Number.isFinite(Number(row.amount)) && Number(row.amount) > 0)
        : hasAccount(debitAccounts, debitAccountId);
    const allocationReady = !capsulesLoading && !capsulesError && capsules.some((capsule) => String(capsule.id) === capsuleId);
    const canSubmit = !accountsLoading && !accountsError && validAmount && Boolean(date)
        && hasAccount(creditAccounts, creditAccountId) && (kind === 'allocation' ? allocationReady : validDebit)
        && (!drawdownActive || (!capsulesLoading && !capsulesError && Boolean(drawdownCapsule)));

    const changeKind = (next: RecordKind) => {
        const nextFields = ACCOUNT_FIELDS[next];
        // Retain compatible picks, but never carry a hidden, invalid leg into a new kind.
        if (!accounts.some((account) => String(account.id) === debitAccountId && nextFields.debitTypes.includes(account.account_type))) setDebitAccountId('');
        if (!accounts.some((account) => String(account.id) === creditAccountId && nextFields.creditTypes.includes(account.account_type))) setCreditAccountId('');
        setKind(next);
        setDrawdownCapsuleId('');
        setDrawdownKind('as_intended');
        setSplitRows([]);
        setError('');
        setConfirmation('');
    };

    const addSplitRow = () => {
        const remainder = splitRows.length ? splitRemainder : numericAmount || 0;
        setSplitRows((rows) => [...rows, {
            accountId: rows.length ? '' : debitAccountId,
            amount: remainder > 0 ? String(remainder) : '',
            memo: '',
        }]);
    };
    const updateSplitRow = (index: number, patch: Partial<SplitRow>) => {
        setSplitRows((rows) => rows.map((row, i) => i === index ? { ...row, ...patch } : row));
    };

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (submitInFlight.current) return;
        setError('');
        setConfirmation('');
        if (!canSubmit) {
            setError(splitActive && !splitBalanced ? '内訳の合計を金額に合わせてください。' : '日付・金額・口座を確認してください。');
            return;
        }
        submitInFlight.current = true;
        setSubmitting(true);
        try {
            if (kind === 'allocation') {
                // Destination legs belong to the server's capsule funding plan.
                await contributeToCapsule(Number(capsuleId), {
                    amount: numericAmount,
                    from_account_id: Number(creditAccountId),
                });
            } else if (drawdownActive) {
                await recordCapsuleDrawdown(Number(drawdownCapsuleId), {
                    amount: numericAmount, from_account_id: Number(creditAccountId),
                    to_account_id: Number(debitAccountId), kind: drawdownKind, date, description,
                });
            } else {
                const legs: TransactionLeg[] = [
                    ...(splitActive ? splitRows.map((row) => ({
                        account_id: Number(row.accountId),
                        debit: Number(row.amount),
                        memo: row.memo.trim() || undefined,
                    })) : [{ account_id: Number(debitAccountId), debit: numericAmount }]),
                    { account_id: Number(creditAccountId), credit: numericAmount },
                ];
                await createTransaction({ date, amount: numericAmount, description, currency, legs });
            }
            // Keep the first debit pick when returning from a split to a simple entry.
            if (splitActive) setDebitAccountId(splitRows[0].accountId);
            setAmount('');
            setDescription('');
            setSplitRows([]);
            setConfirmation(kind === 'allocation' ? '用途を確保しました。' : '取引を記録しました。');
        } catch (failure: unknown) {
            setError(errorMessage(failure));
        } finally {
            submitInFlight.current = false;
            setSubmitting(false);
        }
    };

    return (
        <section className="mx-auto w-full max-w-xl rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6">
            <h2 className="text-lg font-semibold">取引を記録</h2>
            <form onSubmit={handleSubmit} className="mt-6 space-y-5">
                {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
                {(error || accountsError || (kind === 'allocation' && capsulesError)) && (
                    <p role="alert" className="text-sm text-[var(--studio-danger)]">{error || accountsError || capsulesError}</p>
                )}
                {accountsLoading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">口座を読み込んでいます…</p>}
                <fieldset disabled={submitting || accountsLoading || Boolean(accountsError)} className="space-y-5 disabled:opacity-60">
                    <label className="block space-y-2 text-sm">
                        <span className="text-[var(--studio-text-muted)]">記録する内容</span>
                        <select value={kind} onChange={(event) => changeKind(event.target.value as RecordKind)} className={inputClass}>
                            {KINDS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                    </label>
                    {kind !== 'allocation' && (
                        <label className="block space-y-2 text-sm">
                            <span className="text-[var(--studio-text-muted)]">日付</span>
                            <input type="date" required value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} />
                        </label>
                    )}
                    <label className="block space-y-2 text-sm">
                        <span className="text-[var(--studio-text-muted)]">金額（{getCurrencySymbol(currency)}）</span>
                        <input type="number" required min="0.01" step="0.01" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} />
                    </label>
                    {kind !== 'allocation' && (
                        <label className="block space-y-2 text-sm">
                            <span className="text-[var(--studio-text-muted)]">内容</span>
                            <input type="text" value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} />
                        </label>
                    )}
                    {supportsDrawdown && <div className="space-y-3">
                        <label className="block space-y-2 text-sm">
                            <span className="text-[var(--studio-text-muted)]">取り崩す取り置き（任意）</span>
                            <select disabled={capsulesLoading || Boolean(capsulesError)} value={drawdownCapsuleId} onChange={(event) => {
                                const next = event.target.value;
                                setDrawdownCapsuleId(next);
                                setDrawdownKind('as_intended');
                                if (next) {
                                    setSplitRows([]);
                                    const selected = capsules.find((capsule) => String(capsule.id) === next);
                                    if (!selected?.funding_sources?.some((source) => String(source.account_id) === creditAccountId)) setCreditAccountId('');
                                }
                            }} className={inputClass}>
                                <option value="">{capsulesLoading ? '読み込んでいます…' : '選択しない'}</option>
                                {capsules.map((capsule) => <option key={capsule.id} value={capsule.id}>{capsule.name}</option>)}
                            </select>
                        </label>
                        {capsulesError && <p role="alert" className="text-xs text-[var(--studio-danger)]">取り置きを取得できませんでした。{capsulesError}</p>}
                        {drawdownActive && <>
                            <label className="block space-y-2 text-sm">
                                <span className="text-[var(--studio-text-muted)]">区分</span>
                                <select value={drawdownKind} onChange={(event) => setDrawdownKind(event.target.value as CapsuleDrawdownKind)} className={inputClass}>
                                    <option value="as_intended">意図どおり使った</option>
                                    <option value="diverted">他に回した</option>
                                </select>
                            </label>
                            <p className="text-xs text-[var(--studio-text-muted)]">支払元は取り置きの資金源から選びます。使い道の口座は一つにまとめて記録します。</p>
                        </>}
                    </div>}
                    {kind === 'allocation' ? (
                        <label className="block space-y-2 text-sm">
                            <span className="text-[var(--studio-text-muted)]">取り置き</span>
                            <select required disabled={capsulesLoading || Boolean(capsulesError)} value={capsuleId} onChange={(event) => setCapsuleId(event.target.value)} className={inputClass}>
                                <option value="">{capsulesLoading ? '読み込んでいます…' : '選択してください'}</option>
                                {capsules.map((capsule) => <option key={capsule.id} value={capsule.id}>{capsule.name}</option>)}
                            </select>
                            <span className="block text-xs text-[var(--studio-text-faint)]">
                                本日付で記録し、どの口座にいくら置くかは取り置きの資金計画が決めます。
                            </span>
                        </label>
                    ) : !splitActive && (
                        <AccountSelect label={fields.debitLabel} value={debitAccountId} accounts={debitAccounts} onChange={setDebitAccountId} />
                    )}
                    <AccountSelect label={fields.creditLabel} value={creditAccountId} accounts={creditAccounts} onChange={setCreditAccountId} />
                    {supportsSplit && (
                        <div className="space-y-4 rounded-md border border-[var(--studio-border)] p-4">
                            <div className="flex items-center justify-between gap-3">
                                <span className="text-sm text-[var(--studio-text-muted)]">内訳</span>
                                <button type="button" onClick={addSplitRow} className={secondaryButtonClass}>内訳を追加</button>
                            </div>
                            {splitRows.map((row, index) => (
                                <div key={index} className="space-y-3 border-t border-[var(--studio-border)] pt-4">
                                    <div className="flex items-center justify-between">
                                        <span className="text-xs text-[var(--studio-text-muted)]">内訳 {index + 1}</span>
                                        <button type="button" onClick={() => setSplitRows((rows) => rows.filter((_, i) => i !== index))} aria-label={`内訳 ${index + 1} を削除`} className={secondaryButtonClass}>削除</button>
                                    </div>
                                    <AccountSelect label={fields.debitLabel} value={row.accountId} accounts={debitAccounts} onChange={(value) => updateSplitRow(index, { accountId: value })} />
                                    <label className="block space-y-2 text-sm">
                                        <span className="text-[var(--studio-text-muted)]">金額（円）</span>
                                        <input type="number" required min="0.01" step="0.01" inputMode="decimal" value={row.amount} onChange={(event) => updateSplitRow(index, { amount: event.target.value })} className={inputClass} />
                                    </label>
                                    <label className="block space-y-2 text-sm">
                                        <span className="text-[var(--studio-text-muted)]">メモ</span>
                                        <input type="text" value={row.memo} onChange={(event) => updateSplitRow(index, { memo: event.target.value })} className={inputClass} />
                                    </label>
                                </div>
                            ))}
                            {splitActive && (
                                <div className="space-y-2 border-t border-[var(--studio-border)] pt-3">
                                    <p role="status" className={`text-sm ${splitBalanced ? 'text-[var(--studio-positive)]' : 'text-[var(--studio-warning)]'}`}>
                                        残額 {splitRemainder.toLocaleString('ja-JP', { maximumFractionDigits: 2 })} 円
                                    </p>
                                    <button type="button" disabled={splitBalanced} onClick={() => updateSplitRow(splitRows.length - 1, { amount: String((Number(splitRows[splitRows.length - 1].amount) || 0) + splitRemainder) })} className={secondaryButtonClass}>残額を最後の行に反映</button>
                                </div>
                            )}
                        </div>
                    )}
                    <button type="submit" disabled={!canSubmit || submitting} className="w-full rounded-md bg-[var(--studio-accent)] px-4 py-2.5 text-sm font-medium text-[var(--studio-accent-text)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40">
                        {submitting ? '記録しています…' : '記録する'}
                    </button>
                </fieldset>
            </form>
        </section>
    );
}

export default function Record() {
    const { clientId } = useClient();
    return <RecordForClient key={clientId} />;
}
