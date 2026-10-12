import { useEffect, useRef, useState } from 'react';
import { getAccounts, updateAccount } from '../../../api';
import type { Account, AccountRole } from '../../../types';
import { assetErrorMessage, useResource as useAssetData } from '../../useResource';

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

export default function Accounts() {
    const { data: accounts, setData: setAccounts, loading, error, reload } = useAssetData(loadAccounts);
    const [updatingId, setUpdatingId] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const updateInFlight = useRef(false);
    const mounted = useRef(false);

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
            reload();
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(`${account.name}の状態を変更できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            updateInFlight.current = false;
            if (mounted.current) setUpdatingId(null);
        }
    };

    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold">口座</h2>
                    <p className="mt-1 text-xs text-[var(--studio-text-muted)]">無効の口座も表示しています。状態を切り替えると再び利用できます。</p>
                </div>
                <button type="button" onClick={reload} disabled={loading || updatingId !== null} className="rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40">再読み込み</button>
            </div>
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">口座を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">口座一覧を取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {accounts && (accounts.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || updatingId !== null}>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">名称</th><th scope="col" className="px-5 py-3 font-medium">種別</th><th scope="col" className="px-5 py-3 font-medium">役割</th><th scope="col" className="px-5 py-3 font-medium">状態</th></tr>
                        </thead>
                        {ACCOUNT_TYPES.map((type) => {
                            const rows = accounts.filter((account) => account.account_type === type.value);
                            if (!rows.length) return null;
                            return (
                                <tbody key={type.value} className="divide-y divide-[var(--studio-border)]">
                                    <tr className="bg-[var(--studio-bg)]"><th scope="rowgroup" colSpan={4} className="px-5 py-2 text-xs font-medium text-[var(--studio-text-muted)]">{type.label}</th></tr>
                                    {rows.map((account) => (
                                        <tr key={account.id} className={account.is_active ? '' : 'opacity-50'}>
                                            <th scope="row" className="px-5 py-3 font-medium">{account.name}</th>
                                            <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]">{type.label}</td>
                                            <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]">{ROLE_LABELS[account.role] ?? '未設定'}</td>
                                            <td className="px-5 py-3">
                                                <button type="button" role="switch" aria-checked={account.is_active} aria-label={`${account.name}の有効状態`} disabled={loading || Boolean(error) || updatingId !== null} onClick={() => void toggleAccount(account)} className="flex items-center gap-2 whitespace-nowrap rounded-md px-1 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:cursor-not-allowed">
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
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">口座はありません。</p>)}
        </section>
    );
}
