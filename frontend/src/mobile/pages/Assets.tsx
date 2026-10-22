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
import { tr } from '../../studio/i18n';

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
                <p className="text-xs text-[var(--studio-text-muted)]">{tr('残高', 'Balance')}</p>
                <Money value={account.balance} currency={currency} className="text-2xl font-bold" />
                {held > 0 && <p className="mt-1 text-xs text-[var(--studio-text-muted)]">{tr(`うち取り置き ${formatCurrency(held, currency)}・自由に使える額 ${formatCurrency(account.balance - held, currency)}`, `Set aside ${formatCurrency(held, currency)} · free to use ${formatCurrency(account.balance - held, currency)}`)}</p>}
            </div>
            {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
            {!resource.data && !resource.error && <Skeleton lines={2} />}
            {resource.data && resource.data.earmarks.length > 0 && <List title={tr('この口座の取り置き', 'Earmarks in this account')}>
                {resource.data.earmarks.map((row) => <Row key={row.capsule_id} title={row.capsule_name} trailing={<Money value={row.claimed} currency={currency} className="font-semibold" />} />)}
            </List>}
            {resource.data && <section>
                <h2 className="mb-2 px-1 text-xs font-semibold text-[var(--studio-text-muted)]">{tr('最近の記録', 'Recent records')}</h2>
                {resource.data.page.items.length ? <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
                    {resource.data.page.items.map((transaction) => <TransactionRow key={transaction.id} transaction={transaction} types={resource.data!.types} currency={currency} onOpen={(row) => { onClose(); open(row); }} />)}
                </div> : <Empty title={tr('記録はありません', 'No records')} />}
            </section>}
        </div>
    </Sheet>;
}

interface BalanceSheet { total_assets: number; total_liabilities: number; net_worth: number; assets: Array<{ name: string; balance: number }>; liabilities: Array<{ name: string; balance: number }> }

/** 純資産 and every asset and liability account with its balance. */
export default function Assets() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Rows and totals both come from today's balance sheet, as on ホーム; the accounts only say which one to open.
    const load = useCallback(async () => {
        const [accounts, sheet] = await Promise.all([getAccounts(undefined, true), getBalanceSheet() as Promise<BalanceSheet>]);
        const byName = new Map(accounts.map((account) => [account.name, account]));
        const rows = (items: BalanceSheet['assets']) => items.map((item) => ({ ...item, account: byName.get(item.name) ?? null }));
        return { sheet, assets: rows(sheet.assets), liabilities: rows(sheet.liabilities) };
    }, []);
    const resource = useResource(load);
    const [opened, setOpened] = useState<Account | null>(null);
    const assets = resource.data?.assets ?? [];
    const liabilities = resource.data?.liabilities ?? [];
    return <Screen title={tr('資産と口座', 'Assets and accounts')} back={-1}>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!resource.data && !resource.error && <Skeleton lines={4} />}
        {resource.data && <>
            <section className="rounded-3xl bg-[image:var(--mobile-hero)] p-5 text-white shadow-[var(--mobile-shadow-raised)]">
                <p className="text-xs text-white/70">{tr('純資産', 'Net worth')}</p>
                <p className="mt-1 text-3xl font-bold tabular-nums">{formatCurrency(resource.data.sheet.net_worth, currency)}</p>
            </section>
            <List title={`${tr('資産', 'Assets')} ${formatCurrency(resource.data.sheet.total_assets, currency)}`}>
                {assets.length ? assets.map((row) => <Row key={row.name} title={row.name} onClick={row.account ? () => setOpened({ ...row.account as Account, balance: row.balance }) : undefined}
                    trailing={<Money value={row.balance} currency={currency} className="font-semibold" />} />) : <Row title={tr('資産の口座はありません', 'No asset accounts')} chevron={false} />}
            </List>
            <List title={`${tr('負債', 'Liabilities')} ${formatCurrency(resource.data.sheet.total_liabilities, currency)}`}>
                {liabilities.length ? liabilities.map((row) => <Row key={row.name} title={row.name} onClick={row.account ? () => setOpened({ ...row.account as Account, balance: row.balance }) : undefined}
                    trailing={<Money value={row.balance} currency={currency} className="font-semibold" />} />) : <Row title={tr('負債の口座はありません', 'No liability accounts')} chevron={false} />}
            </List>
        </>}
        {opened && <AccountSheet account={opened} currency={currency} onClose={() => setOpened(null)} />}
    </Screen>;
}
