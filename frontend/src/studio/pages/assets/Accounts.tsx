import Overlay from '../../components/Overlay';
import Reconciliation from './Reconciliation';
import AccountEarmarks from './AccountEarmarks';
import { useEffect, useRef, useState } from 'react';
import { useClient } from '../../../context/ClientContext';
import { getAccounts, updateAccount } from '../../../api';
import type { Account, AccountRole } from '../../../types';
import { assetErrorMessage, useResource as useAssetData } from '../../useResource';
import AccountEditor from '../db/AccountEditor';
import { Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';

// Item accounts are returned by the API but omitted by the shared legacy type.
type AssetAccount = Omit<Account, 'account_type'> & {
    account_type: Account['account_type'] | 'item';
};

const ACCOUNT_TYPES: Array<{ value: AssetAccount['account_type']; label: string }> = [
    { value: 'asset', label: '資産' },
    { value: 'liability', label: '負債' },
    { value: 'income', label: '収入' },
    { value: 'expense', label: '費用' },
    { value: 'item', label: '物品' },
];
const ROLE_LABELS: Record<AccountRole, string> = {
    defense: '生活防衛',
    growth: '資産形成',
    earmarked: '用途確保',
    operating: '日常運用',
    unassigned: '未設定',
};

async function loadAccounts(): Promise<AssetAccount[]> {
    // The endpoint filters by one state, so archived accounts need their own request.
    const [active, inactive] = await Promise.all([getAccounts(undefined, true), getAccounts(undefined, false)]);
    const byId = new Map<number, AssetAccount>();
    for (const account of [...inactive, ...active]) byId.set(account.id, account);
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, 'ja'));
}

function AccountDetails({ account, accounts, disabled, onPosted }: {
    account: AssetAccount; accounts: AssetAccount[]; disabled: boolean; onPosted: () => void;
}) {
    const [reconciling, setReconciling] = useState(false);
    const [earmarkRevision, setEarmarkRevision] = useState(0);
    return <>
        <AccountEarmarks key={earmarkRevision} accountId={account.id} accountName={account.name} disabled={disabled} onReconcile={() => setReconciling(true)} />
        {reconciling && <Overlay title={`${account.name}の残高照合`} onClose={() => setReconciling(false)}>
            <Reconciliation account={account} accounts={accounts} disabled={disabled} onPosted={() => {
                // Reconciliation changes current claims as well as the account balance.
                setEarmarkRevision((revision) => revision + 1);
                onPosted();
            }} />
        </Overlay>}
    </>;
}

function AccountsForClient({ subjects, currency }: { subjects: boolean; currency: string }) {
    const { data: accounts, setData: setAccounts, loading, error, reload: reloadAccounts } = useAssetData(loadAccounts);
    const [selectedAccount, setSelectedAccount] = useState<AssetAccount | null>(null);
    const [creating, setCreating] = useState(false);
    const creation = useMutation();
    const [updatingId, setUpdatingId] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const updateInFlight = useRef(false);
    const mounted = useRef(false);
    const types = ACCOUNT_TYPES.filter((type) => subjects
        ? ['income', 'expense'].includes(type.value)
        : ['asset', 'liability', 'item'].includes(type.value));
    const visibleAccounts = accounts?.filter((account) => types.some((type) => type.value === account.account_type));
    const columnCount = subjects ? 3 : 4;
    const disabled = loading || Boolean(error) || updatingId !== null || creation.busy;

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const toggleAccount = async (account: AssetAccount) => {
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
            setConfirmation(`${account.name}を${updated.is_active ? '有効' : '無効'}にしました。`);
            reloadAccounts();
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(`${account.name}の状態を変更できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            updateInFlight.current = false;
            if (mounted.current) setUpdatingId(null);
        }
    };

    return (
        <section className="space-y-4">
            {!subjects && <div className="flex items-center justify-between gap-4">
                <div className="flex gap-2"><button type="button" onClick={() => setCreating(true)} disabled={disabled} className={buttonClass}>口座を作成</button></div>
            </div>}
            <Feedback message={creation.message} />
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">口座を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">口座一覧を取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {visibleAccounts && (visibleAccounts.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || updatingId !== null}>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">名称</th><th scope="col" className="px-5 py-3 font-medium">種別</th>{!subjects && <th scope="col" className="px-5 py-3 font-medium">役割</th>}<th scope="col" className="px-5 py-3 font-medium">状態</th></tr>
                        </thead>
                        {types.map((type) => {
                            const rows = visibleAccounts.filter((account) => account.account_type === type.value);
                            if (!rows.length) return null;
                            return (
                                <tbody key={type.value} className="divide-y divide-[var(--studio-border)]">
                                    <tr className="bg-[var(--studio-bg)]"><th scope="rowgroup" colSpan={columnCount} className="px-5 py-2 text-xs font-medium text-[var(--studio-text-muted)]">{type.label}</th></tr>
                                    {rows.map((account) => (
                                        <tr key={account.id} onClick={() => { if (account.account_type === 'asset' && !disabled) setSelectedAccount(account); }} className={`${account.is_active ? '' : 'opacity-50'} ${account.account_type === 'asset' && !disabled ? 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]' : ''}`}>
                                            <th scope="row" className="px-5 py-3 font-medium">{account.account_type === 'asset' ? <button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={`${account.name}を開く`} onClick={(event) => { event.stopPropagation(); setSelectedAccount(account); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">
                                                {account.name}
                                            </button> : account.name}</th>
                                            <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]">{type.label}</td>
                                            {!subjects && <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]">{ROLE_LABELS[account.role] ?? '未設定'}</td>}
                                            <td className="px-5 py-3">
                                                <button type="button" role="switch" aria-checked={account.is_active} aria-label={`${account.name}の有効状態`} disabled={disabled} onClick={(event) => { event.stopPropagation(); void toggleAccount(account); }} className="flex items-center gap-2 whitespace-nowrap rounded-md px-1 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:cursor-not-allowed">
                                                    <span aria-hidden="true" className={`flex h-5 w-9 items-center rounded-full px-0.5 ${account.is_active ? 'justify-end bg-[var(--studio-accent)]' : 'justify-start bg-[var(--studio-border-strong)]'}`}><span className="h-4 w-4 rounded-full bg-[var(--studio-surface)]" /></span>
                                                    <span>{account.is_active ? '有効' : '無効'}</span>
                                                    {updatingId === account.id && <span className="text-[var(--studio-text-muted)]">更新中…</span>}
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            );
                        })}
                    </table>
                </div>
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">{subjects ? '科目' : '口座'}はありません。</p>)}
            {selectedAccount && <Overlay title={selectedAccount.name} onClose={() => setSelectedAccount(null)}>
                <AccountDetails account={selectedAccount} accounts={accounts ?? []} disabled={disabled} onPosted={reloadAccounts} />
            </Overlay>}
            {creating && accounts && <Overlay title="口座を作成" onClose={() => setCreating(false)}>
                <Feedback error={creation.error} />
                <AccountEditor account={null} accounts={accounts} currency={currency} busy={disabled} onCancel={() => setCreating(false)} onSave={(action) => void creation.run(action, '口座を作成しました。', () => { setCreating(false); reloadAccounts(); })} />
            </Overlay>}
        </section>
    );
}

export default function Accounts({ subjects = false }: { subjects?: boolean }) {
    const { clientId, currentClient } = useClient();
    // Client changes must discard pending confirmations and account-specific drafts.
    return <AccountsForClient key={`${clientId}:${subjects}`} subjects={subjects} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
