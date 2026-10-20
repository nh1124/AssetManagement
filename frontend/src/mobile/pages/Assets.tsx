import { useCallback, useState } from 'react';
import { getAccountEarmarks, getAccounts, getBalanceSheet, getTransactionsPage } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { Account } from '../../types';
import { formatCurrency } from '../../utils/currency';
import { loadAccounts } from '../../studio/pages/db/forms';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { useRecording } from '../components/recording';
import Sheet from '../components/Sheet';
import { TransactionRow } from '../components/transactions';
import { Empty, ErrorNote, List, Money, Row, Skeleton } from '../components/ui';
import { accountTypes } from '../data';

/** One account: what is set aside in it, and its latest records. */
function AccountSheet({ account, currency, onClose }: { account: Account; currency: string; onClose: () => void }) {
    const { open } = useRecording();
    const load = useCallback(async () => {
        const [earmarks, page, accounts] = await Promise.all([
            account.account_type === 'asset' ? getAccountEarmarks(account.id) : Promise.resolve([]),
            getTransactionsPage({ accountId: String(account.id), limit: 10, offset: 0 }), loadAccounts()]);
        return { earmarks, page, types: accountTypes(accounts) };
    }, [account]);
    const resource = useResource(load);
    const held = resource.data?.earmarks.reduce((sum, row) => sum + row.claimed, 0) ?? 0;
    return <Sheet title={account.name} onClose={onClose} tall>
        <div className="space-y-4">
            <div className="rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <p className="text-xs text-[var(--studio-text-muted)]">残高</p>
                <Money value={account.balance} currency={currency} className="text-2xl font-bold" />
                {held > 0 && <p className="mt-1 text-xs text-[var(--studio-text-muted)]">うち取り置き {formatCurrency(held, currency)}・自由に使える額 {formatCurrency(account.balance - held, currency)}</p>}
            </div>
            {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
            {!resource.data && !resource.error && <Skeleton lines={2} />}
            {resource.data && resource.data.earmarks.length > 0 && <List title="この口座の取り置き">
                {resource.data.earmarks.map((row) => <Row key={row.capsule_id} title={row.capsule_name} trailing={<Money value={row.claimed} currency={currency} className="font-semibold" />} />)}
            </List>}
            {resource.data && <section>
                <h2 className="mb-2 px-1 text-xs font-semibold text-[var(--studio-text-muted)]">最近の記録</h2>
                {resource.data.page.items.length ? <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
                    {resource.data.page.items.map((transaction) => <TransactionRow key={transaction.id} transaction={transaction} types={resource.data!.types} currency={currency} onOpen={(row) => { onClose(); open(row); }} />)}
                </div> : <Empty title="記録はありません" />}
            </section>}
        </div>
    </Sheet>;
}

/** 純資産 and every asset and liability account with its balance. */
export default function Assets() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Totals come from the balance sheet, as on ホーム; the rows are the accounts with their balances.
    const load = useCallback(async () => {
        const [accounts, sheet] = await Promise.all([getAccounts(undefined, true),
            getBalanceSheet() as Promise<{ total_assets: number; total_liabilities: number; net_worth: number }>]);
        return { accounts, sheet };
    }, []);
    const resource = useResource(load);
    const [opened, setOpened] = useState<Account | null>(null);
    const assets = resource.data?.accounts.filter((account) => account.account_type === 'asset') ?? [];
    const liabilities = resource.data?.accounts.filter((account) => account.account_type === 'liability') ?? [];
    return <Screen title="資産と口座" back={-1}>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!resource.data && !resource.error && <Skeleton lines={4} />}
        {resource.data && <>
            <section className="rounded-3xl bg-[image:var(--mobile-hero)] p-5 text-white shadow-[var(--mobile-shadow-raised)]">
                <p className="text-xs text-white/70">純資産</p>
                <p className="mt-1 text-3xl font-bold tabular-nums">{formatCurrency(resource.data.sheet.net_worth, currency)}</p>
            </section>
            <List title={`資産 ${formatCurrency(resource.data.sheet.total_assets, currency)}`}>
                {assets.length ? assets.map((account) => <Row key={account.id} title={account.name} onClick={() => setOpened(account)}
                    trailing={<Money value={account.balance} currency={currency} className="font-semibold" />} />) : <Row title="資産の口座はありません" chevron={false} />}
            </List>
            <List title={`負債 ${formatCurrency(resource.data.sheet.total_liabilities, currency)}`}>
                {liabilities.length ? liabilities.map((account) => <Row key={account.id} title={account.name} onClick={() => setOpened(account)}
                    trailing={<Money value={Math.abs(account.balance)} currency={currency} className="font-semibold" />} />) : <Row title="負債の口座はありません" chevron={false} />}
            </List>
        </>}
        {opened && <AccountSheet account={opened} currency={currency} onClose={() => setOpened(null)} />}
    </Screen>;
}
