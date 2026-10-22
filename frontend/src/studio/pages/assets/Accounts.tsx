import Overlay from '../../components/Overlay';
import Reconciliation from './Reconciliation';
import AccountEarmarks from './AccountEarmarks';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useClient } from '../../../context/ClientContext';
import { getAccountFlows, getAccounts, updateAccount } from '../../../api';
import type { Account } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { clientToday } from '../../datetime';
import { assetErrorMessage, useResource as useAssetData } from '../../useResource';
import AccountEditor from '../db/AccountEditor';
import { ActiveSwitch, Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';
import { tr } from '../../i18n';

const accountTypes = (): Array<{ value: Account['account_type']; label: string }> => [
    { value: 'asset', label: tr('資産', 'Assets') },
    { value: 'liability', label: tr('負債', 'Liabilities') },
    { value: 'income', label: tr('収入', 'Income') },
    { value: 'expense', label: tr('費用', 'Expenses') },
];

async function loadAccounts(): Promise<Account[]> {
    // The endpoint filters by one state, so archived accounts need their own request.
    const [active, inactive] = await Promise.all([getAccounts(undefined, true), getAccounts(undefined, false)]);
    const byId = new Map<number, Account>();
    for (const account of [...inactive, ...active]) byId.set(account.id, account);
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, 'ja'));
}

const noFlows = async (): Promise<Map<number, number>> => new Map();

function AccountDetails({ account, accounts, disabled, onPosted }: {
    account: Account; accounts: Account[]; disabled: boolean; onPosted: () => void;
}) {
    const [reconciling, setReconciling] = useState(false);
    const [earmarkRevision, setEarmarkRevision] = useState(0);
    return <>
        <AccountEarmarks key={earmarkRevision} accountId={account.id} accountName={account.name} disabled={disabled} onReconcile={() => setReconciling(true)} />
        {reconciling && <Overlay title={tr(`${account.name}の残高照合`, `Reconcile ${account.name}`)} onClose={() => setReconciling(false)}>
            <Reconciliation account={account} accounts={accounts} disabled={disabled} onPosted={() => {
                // Reconciliation changes current claims as well as the account balance.
                setEarmarkRevision((revision) => revision + 1);
                onPosted();
            }} />
        </Overlay>}
    </>;
}

function AccountsForClient({ subjects, currency, timezone }: { subjects: boolean; currency: string; timezone: string }) {
    const { data: accounts, setData: setAccounts, loading, error, reload: reloadAccounts } = useAssetData(loadAccounts);
    const month = clientToday(timezone).slice(0, 7);
    // A subject's lifetime total says little; this month's amount is what it booked now.
    const loadMonth = useCallback(async () => {
        const [year, monthNumber] = month.split('-').map(Number);
        const flows = await getAccountFlows({
            startDate: `${month}-01`, endDate: `${month}-${String(new Date(year, monthNumber, 0).getDate()).padStart(2, '0')}`,
            accountTypes: ['income', 'expense'], includeZero: true,
        });
        return new Map(flows.accounts.map((row) => [row.account_id, row.normal_balance_delta]));
    }, [month]);
    const thisMonth = useAssetData(subjects ? loadMonth : noFlows);
    const [selectedAccount, setSelectedAccount] = useState<Account | null>(null);
    const [creating, setCreating] = useState(false);
    const creation = useMutation();
    const [updatingId, setUpdatingId] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const updateInFlight = useRef(false);
    const mounted = useRef(false);
    const types = accountTypes().filter((type) => subjects
        ? ['income', 'expense'].includes(type.value)
        : ['asset', 'liability'].includes(type.value));
    const visibleAccounts = accounts?.filter((account) => types.some((type) => type.value === account.account_type));
    const disabled = loading || Boolean(error) || updatingId !== null || creation.busy;

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const toggleAccount = async (account: Account) => {
        if (updateInFlight.current || loading || error) return;
        updateInFlight.current = true;
        setUpdatingId(account.id);
        setOperationError('');
        setConfirmation('');
        try {
            const updated = await updateAccount(account.id, { is_active: !account.is_active });
            if (!mounted.current) return;
            // Preserve the confirmed state if the subsequent list refresh fails.
            setAccounts((rows) => rows?.map((row) => row.id === updated.id ? { ...row, is_active: updated.is_active } : row) ?? null);
            setConfirmation(tr(`${account.name}を${updated.is_active ? '有効' : '無効'}にしました。`, `${account.name} ${updated.is_active ? 'activated' : 'deactivated'}.`));
            reloadAccounts();
            // The month's amounts cover active subjects only.
            thisMonth.reload();
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(tr(`${account.name}の状態を変更できませんでした。${assetErrorMessage(failure)}`, `Could not change the state of ${account.name}. ${assetErrorMessage(failure)}`));
        } finally {
            updateInFlight.current = false;
            if (mounted.current) setUpdatingId(null);
        }
    };

    return (
        <section className="space-y-4">
            {!subjects && <div className="flex items-center justify-between gap-4">
                <div className="flex gap-2"><button type="button" onClick={() => setCreating(true)} disabled={disabled} className={buttonClass}>{tr('口座を作成', 'Create account')}</button></div>
            </div>}
            <Feedback message={creation.message} />
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('口座を読み込んでいます…', 'Loading accounts…')}</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('口座一覧を取得できませんでした。', 'Could not load accounts. ')}{error}</p>}
            {thisMonth.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('今月の額を取得できませんでした。', 'Could not load this month’s amounts. ')}{thisMonth.error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {visibleAccounts && (visibleAccounts.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || updatingId !== null}>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">{tr('名称', 'Name')}</th>{subjects && <th scope="col" className="px-5 py-3 text-right font-medium">{tr('今月', 'This month')}</th>}{!subjects && <th scope="col" className="px-5 py-3 text-right font-medium">{tr('残高', 'Balance')}</th>}<th scope="col" className="px-5 py-3 font-medium">{tr('状態', 'Status')}</th></tr>
                        </thead>
                        {types.map((type) => {
                            const rows = visibleAccounts.filter((account) => account.account_type === type.value);
                            if (!rows.length) return null;
                            return (
                                <tbody key={type.value} className="divide-y divide-[var(--studio-border)]">
                                    <tr className="bg-[var(--studio-bg)]"><th scope="rowgroup" colSpan={3} className="px-5 py-2 text-xs font-medium text-[var(--studio-text-muted)]">{type.label}</th></tr>
                                    {rows.map((account) => (
                                        <tr key={account.id} onClick={() => { if (account.account_type === 'asset' && !disabled) setSelectedAccount(account); }} className={`${account.is_active ? '' : 'opacity-50'} ${account.account_type === 'asset' && !disabled ? 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]' : ''}`}>
                                            <th scope="row" className="px-5 py-3 font-medium">{account.account_type === 'asset' ? <button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={tr(`${account.name}を開く`, `Open ${account.name}`)} onClick={(event) => { event.stopPropagation(); setSelectedAccount(account); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">
                                                {account.name}
                                            </button> : account.name}</th>
                                            {/* A subject's total since its first entry is not a balance to reconcile. */}
                                            {subjects && <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{thisMonth.data?.has(account.id) ? formatCurrency(thisMonth.data.get(account.id) ?? 0, currency) : '—'}</td>}
                                            {!subjects && <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatCurrency(account.balance, currency)}</td>}
                                            <td className="px-5 py-3">
                                                <ActiveSwitch name={account.name} active={account.is_active} disabled={disabled} busy={updatingId === account.id} onToggle={() => void toggleAccount(account)} />
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            );
                        })}
                    </table>
                </div>
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">{subjects ? tr('科目はありません。', 'No income or expense accounts.') : tr('口座はありません。', 'No accounts.')}</p>)}
            {selectedAccount && <Overlay title={selectedAccount.name} onClose={() => setSelectedAccount(null)}>
                <AccountDetails account={selectedAccount} accounts={accounts ?? []} disabled={disabled} onPosted={reloadAccounts} />
            </Overlay>}
            {creating && accounts && <Overlay title={tr('口座を作成', 'Create account')} onClose={() => setCreating(false)}>
                <Feedback error={creation.error} />
                <AccountEditor account={null} currency={currency} busy={disabled} onCancel={() => setCreating(false)} onSave={(action) => void creation.run(action, tr('口座を作成しました。', 'Account created.'), () => { setCreating(false); reloadAccounts(); })} />
            </Overlay>}
        </section>
    );
}

export default function Accounts({ subjects = false }: { subjects?: boolean }) {
    const { clientId, currentClient } = useClient();
    // Client changes must discard pending confirmations and account-specific drafts.
    return <AccountsForClient key={`${clientId}:${subjects}`} subjects={subjects} currency={currentClient?.general_settings?.currency || 'JPY'}
        timezone={currentClient?.general_settings?.timezone || 'UTC'} />;
}
