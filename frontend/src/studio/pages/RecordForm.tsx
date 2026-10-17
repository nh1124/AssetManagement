import { useConfirm } from '../components/useConfirm';
import ClosedPeriodWarning from '../components/ClosedPeriodWarning';
import DrawdownClaim from '../components/DrawdownClaim';
import { OverlayFooter } from '../components/Overlay';
import { OverlayFooterContext } from '../components/overlayContext';
import { clientToday, useTimezone } from '../datetime';
import { useContext, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { isAxiosError } from 'axios';
import { contributeToCapsule, createTransaction, getAccounts, getCapsules, recordCapsuleDrawdown, updateTransaction, getCapsuleReservations } from '../../api';
import { useClient } from '../../context/ClientContext';
import { formatCurrency, getCurrencySymbol } from '../../utils/currency';
import type { Account, Capsule, CapsuleDrawdownKind, Transaction, TransactionLeg } from '../../types';

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

export default function RecordForm({ existing, onSaved, onCancel, onDelete, deleting = false }: {
    existing?: Transaction; onSaved?: () => void; onCancel?: () => void;
    onDelete?: () => void; deleting?: boolean;
}) {
    const formId = useId();
    // The overlay draws the frame and the title, so the standalone card chrome
    // would nest one box inside another and repeat the heading.
    // undefined means no overlay; null is an overlay whose footer has not mounted yet.
    const inOverlay = useContext(OverlayFooterContext) !== undefined;
    const confirm = useConfirm();
    const { clientId, currentClient } = useClient();
    const identified = currentClient?.id === clientId;
    // Money is per-currency here and is never totalled across currencies, so
    // edits retain the entry's denomination instead of relabelling its money.
    const currency = existing?.currency || currentClient?.general_settings?.currency || 'JPY';
    const [accounts, setAccounts] = useState<RecordAccount[]>([]);
    const [capsules, setCapsules] = useState<Capsule[]>([]);
    const [accountsLoading, setAccountsLoading] = useState(true);
    const [capsulesLoading, setCapsulesLoading] = useState(true);
    const [accountsError, setAccountsError] = useState('');
    const [capsulesError, setCapsulesError] = useState('');
    const [kind, setKind] = useState<RecordKind>('expense');
    const timezone = useTimezone();
    const [dateEdit, setDate] = useState<string | null>(existing?.date ?? null);
    const date = dateEdit ?? clientToday(timezone);
    const [amount, setAmount] = useState(existing ? String(existing.amount) : '');
    const [description, setDescription] = useState(existing?.description ?? '');
    const [debitAccountId, setDebitAccountId] = useState('');
    const [creditAccountId, setCreditAccountId] = useState('');
    const [capsuleId, setCapsuleId] = useState('');
    const [drawdownCapsuleId, setDrawdownCapsuleId] = useState('');
    const [drawdownKind, setDrawdownKind] = useState<CapsuleDrawdownKind>('as_intended');
    const [claimRevision, setClaimRevision] = useState(0);
    const [splitRows, setSplitRows] = useState<SplitRow[]>([]);
    // Keep every original leg, memo and attribution; compound entries cannot
    // be faithfully reconstructed from the derived from/to account pair.
    const [editLegs, setEditLegs] = useState<TransactionLeg[]>(() => existing?.legs?.map((leg) => ({
        account_id: leg.account_id, debit: leg.debit ?? 0, credit: leg.credit ?? 0,
        memo: leg.memo, capsule_id: leg.capsule_id,
    })) ?? (existing ? [
        { account_id: existing.to_account_id ?? 0, debit: existing.amount },
        { account_id: existing.from_account_id ?? 0, credit: existing.amount },
    ] : []));
    const changeLeg = (index: number, patch: Partial<TransactionLeg>) => {
        setEditLegs((rows) => rows.map((row, i) => i === index ? { ...row, ...patch } : row));
    };
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const submitInFlight = useRef(false);

    useEffect(() => {
        let stale = false;
        void (existing ? Promise.all([getAccounts(undefined, true), getAccounts(undefined, false)]).then(([active, inactive]) => [...active, ...inactive]) : getAccounts()).then((data) => {
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
    }, [existing]);

    const fields = ACCOUNT_FIELDS[kind];
    const debitAccounts = accounts.filter((account) => fields.debitTypes.includes(account.account_type));
    const supportsDrawdown = kind === 'expense' || kind === 'purchase';
    const drawdownCapsule = supportsDrawdown ? capsules.find((capsule) => String(capsule.id) === drawdownCapsuleId) : undefined;
    const drawdownActive = supportsDrawdown && Boolean(drawdownCapsuleId);
    const creditAccounts = accounts.filter((account) => fields.creditTypes.includes(account.account_type)
        && (!drawdownActive || drawdownCapsule?.funding_sources?.some((source) => source.account_id === account.id)));
    const drawdownAccount = drawdownActive ? creditAccounts.find((account) => String(account.id) === creditAccountId) : undefined;
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
    const canCreate = !accountsLoading && !accountsError && validAmount && Boolean(date)
        && hasAccount(creditAccounts, creditAccountId) && (kind === 'allocation' ? allocationReady : validDebit)
        && (!drawdownActive || (!capsulesLoading && !capsulesError && Boolean(drawdownCapsule)));

    const factor = ['JPY', 'KRW'].includes(currency) ? 1 : 100;
    const units = (value: number) => Math.round(value * factor);
    const editBalanced = editLegs.length >= 2 && editLegs.every((leg) => accounts.some((account) => account.id === leg.account_id)
        && Number.isFinite(leg.debit ?? 0) && Number.isFinite(leg.credit ?? 0)
        && ((leg.debit ?? 0) > 0 ? (leg.credit ?? 0) === 0 : (leg.credit ?? 0) > 0 && (leg.debit ?? 0) === 0))
        && editLegs.reduce((sum, leg) => sum + units(leg.debit ?? 0), 0) === units(numericAmount)
        && editLegs.reduce((sum, leg) => sum + units(leg.credit ?? 0), 0) === units(numericAmount);
    const canSubmit = identified && (existing ? !accountsLoading && !accountsError && validAmount && Boolean(date) && editBalanced : canCreate);

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
        if (submitInFlight.current || deleting) return;
        setError('');
        setConfirmation('');
        if (!canSubmit) {
            setError(splitActive && !splitBalanced ? '内訳の合計を金額に合わせてください。' : '日付・金額・口座を確認してください。');
            return;
        }
        submitInFlight.current = true;
        setSubmitting(true);
        try {
            let closedPeriod: string | null | undefined;
            if (existing) {
                const reservations = await getCapsuleReservations(existing.id);
                const affected = reservations.filter((row) => row.status !== 'rejected').map((row) => row.capsule_name || '取り置き').join('、');
                if (!(await confirm(`「${currentClient?.name ?? ''}」の取引 #${existing.id}を ${formatCurrency(numericAmount, currency)}（${currency}）に編集しますか？\n元の取引が発火させた取り置き予約を取り消して再評価するため、確保額・取り置きが変わる場合があります。${affected ? `\n対象：${affected}` : ''}\n紐づく取り崩し記録は再計算・更新されません。`, '保存する'))) return;
                const result = await updateTransaction(existing.id, { date, amount: numericAmount, description, currency, legs: editLegs });
                setConfirmation(`取引を更新しました。${result.closed_period ? ` ${result.closed_period} は締め済みです。締め後の変更として報告されます。` : ''}`);
                onSaved?.();
                return;
            }
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
                // A second entry needs the remaining claim after this release.
                setClaimRevision((value) => value + 1);
            } else {
                const legs: TransactionLeg[] = [
                    ...(splitActive ? splitRows.map((row) => ({
                        account_id: Number(row.accountId),
                        debit: Number(row.amount),
                        memo: row.memo.trim() || undefined,
                    })) : [{ account_id: Number(debitAccountId), debit: numericAmount }]),
                    { account_id: Number(creditAccountId), credit: numericAmount },
                ];
                const result = await createTransaction({ date, amount: numericAmount, description, currency, legs });
                closedPeriod = result.closed_period;
            }
            // Keep the first debit pick when returning from a split to a simple entry.
            if (splitActive) setDebitAccountId(splitRows[0].accountId);
            setAmount('');
            setDescription('');
            setSplitRows([]);
            setConfirmation(kind === 'allocation' ? '用途を確保しました。' : `取引を記録しました。${closedPeriod ? ` ${closedPeriod} は締め済みです。締め後の変更として報告されます。` : ''}`);
        } catch (failure: unknown) {
            setError(errorMessage(failure));
        } finally {
            submitInFlight.current = false;
            setSubmitting(false);
        }
    };

    // Explicit form ownership keeps native validation when actions move into the overlay footer.
    const saveButton = (fullWidth = false) => <button type="submit" form={formId} disabled={!canSubmit || submitting || deleting} className={`${fullWidth ? 'w-full ' : ''}rounded-md bg-[var(--studio-accent)] px-4 py-2.5 text-sm font-medium text-[var(--studio-accent-text)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40`}>
        {submitting ? '保存しています…' : existing ? '保存' : '記録する'}
    </button>;

    return (
        <section className={inOverlay ? 'w-full' : 'mx-auto w-full max-w-xl rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6'}>
            {existing && !inOverlay && <h2 className="text-lg font-semibold">取引 #{existing.id}「{existing.description || '内容未入力'}」を編集</h2>}
            <form id={formId} onSubmit={handleSubmit} className={inOverlay ? 'space-y-5' : 'mt-6 space-y-5'}>
                {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
                {(error || accountsError || (kind === 'allocation' && capsulesError)) && (
                    <p role="alert" className="text-sm text-[var(--studio-danger)]">{error || accountsError || capsulesError}</p>
                )}
                {accountsLoading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">口座を読み込んでいます…</p>}
                <fieldset disabled={submitting || deleting || accountsLoading || Boolean(accountsError) || !identified} className="space-y-5 disabled:opacity-60">
                    {!existing && <label className="block space-y-2 text-sm">
                        <span className="text-[var(--studio-text-muted)]">記録する内容</span>
                        <select value={kind} onChange={(event) => changeKind(event.target.value as RecordKind)} className={inputClass}>
                            {KINDS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                    </label>}
                    {(existing || kind !== 'allocation') && (
                        <label className="block space-y-2 text-sm">
                            <span className="text-[var(--studio-text-muted)]">日付</span>
                            <input type="date" required value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} />
                            <ClosedPeriodWarning date={date} />
                        </label>
                    )}
                    <div><label className="block space-y-2 text-sm">
                        <span className="text-[var(--studio-text-muted)]">金額（{getCurrencySymbol(currency)}）</span>
                        <input type="number" required min="0.01" step="0.01" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} />
                    </label>
                        {!existing && drawdownCapsule && drawdownAccount && <DrawdownClaim key={`${clientId}:${drawdownCapsule.id}:${drawdownAccount.id}:${currency}:${claimRevision}`} accountId={drawdownAccount.id} accountName={drawdownAccount.name} capsuleId={drawdownCapsule.id} currency={currency} />}
                    </div>
                    {(existing || kind !== 'allocation') && (
                        <label className="block space-y-2 text-sm">
                            <span className="text-[var(--studio-text-muted)]">内容</span>
                            <input type="text" value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} />
                        </label>
                    )}
                    {!existing && supportsDrawdown && <div className="space-y-3">
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
                    <p className="text-xs text-[var(--studio-text-muted)]">支払元は取り置きの資金源から選びます。</p>
                        </>}
                    </div>}
                    {!existing && <>{kind === 'allocation' ? (
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
                                        <span className="text-[var(--studio-text-muted)]">金額（{currency}）</span>
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
                                        残額 {formatCurrency(splitRemainder, currency)}（{currency}）
                                    </p>
                                    <button type="button" disabled={splitBalanced} onClick={() => updateSplitRow(splitRows.length - 1, { amount: String((Number(splitRows[splitRows.length - 1].amount) || 0) + splitRemainder) })} className={secondaryButtonClass}>残額を最後の行に反映</button>
                                </div>
                            )}
                        </div>
                    )}
                    </>}
                    {existing && <div className="space-y-4">
                        <h3 className="text-sm font-medium">仕訳の内訳</h3>
                        <p className="text-xs text-[var(--studio-warning)]">取り置きの帰属は各行で指定します。この取引に紐づく取り崩し記録の金額・区分は、編集しても再計算・更新されません。</p>
                        {editLegs.map((leg, index) => <div key={index} className="space-y-3 rounded-md border border-[var(--studio-border)] p-3">
                            <AccountSelect label={`内訳 ${index + 1} の口座`} value={String(leg.account_id || '')} accounts={accounts} onChange={(value) => changeLeg(index, { account_id: Number(value) })} />
                            <div className="grid gap-3 sm:grid-cols-2">
                                <label className="space-y-2 text-sm"><span>借方（{currency}）</span><input required type="number" min="0" step={1 / factor} value={leg.debit ?? 0} onChange={(event) => changeLeg(index, { debit: Number(event.target.value) })} className={inputClass} /></label>
                                <label className="space-y-2 text-sm"><span>貸方（{currency}）</span><input required type="number" min="0" step={1 / factor} value={leg.credit ?? 0} onChange={(event) => changeLeg(index, { credit: Number(event.target.value) })} className={inputClass} /></label>
                            </div>
                            <label className="block space-y-2 text-sm"><span>取り置き（任意）</span><select value={leg.capsule_id ?? ''} disabled={capsulesLoading || Boolean(capsulesError)} onChange={(event) => changeLeg(index, { capsule_id: event.target.value ? Number(event.target.value) : null })} className={inputClass}>
                                <option value="">指定しない</option>
                                {leg.capsule_id != null && !capsules.some((row) => row.id === leg.capsule_id) && <option value={leg.capsule_id}>#{leg.capsule_id}（一覧にありません）</option>}
                                {capsules.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
                            </select></label>
                            <label className="block space-y-2 text-sm"><span>メモ</span><input value={leg.memo ?? ''} onChange={(event) => changeLeg(index, { memo: event.target.value })} className={inputClass} /></label>
                            <button type="button" onClick={() => setEditLegs((rows) => rows.filter((_, i) => i !== index))} className={secondaryButtonClass}>内訳を削除</button>
                        </div>)}
                        <button type="button" onClick={() => setEditLegs((rows) => [...rows, { account_id: 0, debit: 0, credit: 0 }])} className={secondaryButtonClass}>内訳を追加</button>
                        {!editBalanced && <p className="text-xs text-[var(--studio-warning)]">借方・貸方の合計を、それぞれ取引の金額に合わせてください。</p>}
                        {capsulesError && <p role="alert" className="text-xs text-[var(--studio-danger)]">取り置きを取得できませんでした。既存の帰属を保持します。{capsulesError}</p>}
                    </div>}
                </fieldset>
                <OverlayFooter fallback={<>
                    {saveButton(true)}
                    {onCancel && <button type="button" disabled={submitting || deleting} onClick={onCancel} className={secondaryButtonClass}>キャンセル</button>}
                </>}>
                    {onDelete && <button type="button" disabled={submitting || deleting || !identified} onClick={onDelete} className={`${secondaryButtonClass} mr-auto text-[var(--studio-danger)]`}>{deleting ? '削除中…' : '削除'}</button>}
                    {saveButton()}
                </OverlayFooter>
            </form>
        </section>
    );
}
