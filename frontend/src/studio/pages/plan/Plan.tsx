import Overlay from '../../components/Overlay';
import { clientToday, useTimezone } from '../../datetime';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { getBudgetSummary, getScheduledTransactions } from '../../../api';
import { planCheck, type GoalPlanCheck } from '../../../api/goalPlan';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import AccountEditor from '../db/AccountEditor';
import { buttonClass, inputClass, loadAccounts, primaryClass, useMutation, type DatabaseAccount } from '../db/forms';
import GoalPlanDialog from '../goals/GoalPlanDialog';
import { useNotifications } from '../../notificationContext';
import MonthPicker from '../ledger/MonthPicker';
import MonthCopy from './MonthCopy';
import { AccountOverlay, EarmarkOverlay, type OverlayContext } from './BudgetOverlay';
import { SCOPES, buildModel, earmarkMatches, rowMatches, type BudgetSummary, type Scope } from './budgetRows';
import BudgetTable from './BudgetTable';

interface Filters { query: string; scope: Scope }
const FILTERS_KEY = 'studio.budget.filters';

function storedFilters(): Filters {
    try {
        const stored = JSON.parse(localStorage.getItem(FILTERS_KEY) ?? '{}') as Partial<Filters>;
        return {
            query: '',
            scope: SCOPES.some((scope) => scope.value === stored.scope) ? stored.scope as Scope : 'all',
        };
    } catch {
        return { query: '', scope: 'all' };
    }
}

const loadSummary = (period: string): Promise<BudgetSummary> => getBudgetSummary(period, { include_unset: true });

/** 項目を追加: a new account or subject, made with the database screen's editor. */
function AddItem({ currency, busy, error, onSave, onClose }: {
    currency: string; busy: boolean; error: string;
    onSave: (action: () => Promise<unknown>) => void; onClose: () => void;
}) {
    const accounts = useResource(loadAccounts);
    return <Overlay title="項目を追加（口座・勘定科目）" onClose={onClose}>
        <p className="mb-4 text-xs text-[var(--studio-text-muted)]">作成すると計画に「未設定」で並びます。</p>
        <Feedback loading={accounts.loading} error={error || accounts.error} />
        {accounts.data && <AccountEditor account={null} initialType="expense" currency={currency} busy={busy} onSave={onSave} onCancel={onClose} />}
    </Overlay>;
}

/** その他: the operations used now and then, out of the toolbar. */
function MoreMenu({ disabled, items }: { disabled: boolean; items: Array<{ label: string; onSelect: () => void }> }) {
    const menu = useRef<HTMLDetailsElement>(null);
    useEffect(() => {
        // A click anywhere else closes the menu, as a native menu would.
        const close = (event: PointerEvent) => {
            if (menu.current?.open && !menu.current.contains(event.target as Node)) menu.current.open = false;
        };
        document.addEventListener('pointerdown', close);
        return () => document.removeEventListener('pointerdown', close);
    }, []);
    return <details ref={menu} className="relative">
        <summary aria-disabled={disabled} className={`${buttonClass} cursor-pointer list-none ${disabled ? 'pointer-events-none opacity-40' : ''}`}>その他 ▾</summary>
        <div role="menu" className="absolute right-0 z-10 mt-1 w-48 rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] py-1 shadow-lg">
            {items.map((item) => <button key={item.label} type="button" role="menuitem" onClick={() => { if (menu.current) menu.current.open = false; item.onSelect(); }}
                className="block w-full px-3 py-2 text-left text-sm hover:bg-[var(--studio-accent-soft)]">{item.label}</button>)}
        </div>
    </details>;
}

/** ゴールの積立: what the goal's 積立設定 puts aside this month per account, beside what the plan does. */
function GoalContribution({ check, error, currency, disabled, onCreate }: {
    check: GoalPlanCheck | null; error: string; currency: string; disabled: boolean; onCreate: () => void;
}) {
    const money = (amount: number) => formatCurrency(amount, currency);
    if (error) return <Feedback error={`ゴールの積立を取得できませんでした。${error}`} />;
    if (!check?.goal) return null;
    const differs = check.accounts.some((row) => Math.abs(row.difference) >= 1);
    return <details open={differs || !check.reflected} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
        <summary className="cursor-pointer text-xs">
            <span className="font-semibold">ゴールの積立</span>
            <span className="ml-2 tabular-nums text-[var(--studio-text-muted)]">ゴール「{check.goal.name}」の積立設定 {money(check.contribution)} ／ 計画 {money(check.planned)}（差 {check.difference >= 0 ? '+' : ''}{money(check.difference)}）</span>
            {!check.reflected && check.contribution > 0 && <span className="ml-2 text-[var(--studio-warning)]">この月はゴールから計画を作成していません</span>}
        </summary>
        <div className="mt-3 space-y-3">
            {check.accounts.length ? <table className="w-full text-left text-sm">
                <thead className="text-xs text-[var(--studio-text-muted)]"><tr>{['口座', '積立設定', '計画（配分・取り置き）', '差'].map((label) => <th key={label} scope="col" className="py-1.5 pr-4 font-medium">{label}</th>)}</tr></thead>
                <tbody className="divide-y divide-[var(--studio-border)]">
                    {check.accounts.map((row) => <tr key={row.account_id}>
                        <th scope="row" className="py-1.5 pr-4 font-normal">{row.name}</th>
                        <td className="py-1.5 pr-4 tabular-nums">{money(row.contribution)}</td>
                        <td className="py-1.5 pr-4 tabular-nums">{money(row.planned)}</td>
                        <td className={`py-1.5 pr-4 tabular-nums ${Math.abs(row.difference) >= 1 ? 'text-[var(--studio-warning)]' : 'text-[var(--studio-text-muted)]'}`}>{row.difference >= 0 ? '+' : ''}{money(row.difference)}</td>
                    </tr>)}
                </tbody>
            </table> : <p className="text-xs text-[var(--studio-text-muted)]">この月の積立設定はありません。</p>}
            <button type="button" disabled={disabled} onClick={onCreate} className={buttonClass}>ゴールから計画を作成</button>
        </div>
    </details>;
}

function MonthlyPlan({ period, currency, clientName, filters, picker, onFilters, onBusy }: {
    period: string; currency: string; clientName?: string; filters: Filters; picker: ReactNode;
    onFilters: (filters: Filters) => void; onBusy: (busy: boolean) => void;
}) {
    const load = useCallback(() => loadSummary(period), [period]);
    const resource = useResource(load);
    const loadCheck = useCallback(() => planCheck(period), [period]);
    const check = useResource(loadCheck);
    const loadScheduled = useCallback(() => getScheduledTransactions(period), [period]);
    const scheduled = useResource(loadScheduled);
    const accounts = useResource(loadAccounts);
    const refresh = () => { resource.reload(); check.reload(); };
    const mutation = useMutation();
    const notifications = useNotifications();
    const [copyBusy, setCopyBusy] = useState(false);
    const [copying, setCopying] = useState(false);
    const [planning, setPlanning] = useState(false);
    const [adding, setAdding] = useState(false);
    const [created, setCreated] = useState<number | null>(null);
    const [message, setMessage] = useState('');
    const [openAccount, setOpenAccount] = useState<string | null>(null);
    const [openEarmark, setOpenEarmark] = useState<string | null>(null);
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || copyBusy || !clientName;

    const model = useMemo(() => resource.data && accounts.data
        ? buildModel(resource.data, accounts.data as DatabaseAccount[], scheduled.data?.items ?? [])
        : null, [resource.data, accounts.data, scheduled.data]);
    const names = useMemo(() => new Map((accounts.data ?? []).map((account) => [account.id, account.name])), [accounts.data]);
    const narrowed = Boolean(filters.query.trim()) || filters.scope !== 'all';
    const rows = model?.accounts.filter((row) => rowMatches(row, filters.query, filters.scope) || (row.accountId != null && row.accountId === created)) ?? [];
    const earmarks = model?.earmarks.filter((earmark) => earmarkMatches(earmark, filters.query, filters.scope)) ?? [];
    const accountRow = model?.accounts.find((row) => row.key === openAccount);
    const earmarkRow = model?.earmarks.find((earmark) => earmark.key === openEarmark);
    const context: OverlayContext = {
        period, currency, clientName, planId: resource.data?.plan_id ?? null,
        accountName: (id) => id == null ? '—' : names.get(id) ?? `#${id}`,
        onChanged: refresh,
    };
    const add = (action: () => Promise<unknown>) => void mutation.run(async () => {
        const account = await action() as { id: number };
        setCreated(account.id);
    }, '項目を追加しました。一覧で色付きで表示しています。', () => {
        setAdding(false);
        accounts.reload();
        resource.reload();
    });

    return <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
            {picker}
            <div className="w-48"><input type="search" aria-label="名前で検索" placeholder="名前で検索" value={filters.query} onChange={(event) => onFilters({ ...filters, query: event.target.value })} className={inputClass} /></div>
            <div role="group" aria-label="表示する項目" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {SCOPES.map((scope) => <button key={scope.value} type="button" aria-pressed={filters.scope === scope.value} onClick={() => onFilters({ ...filters, scope: scope.value })} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{scope.label}</button>)}
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
                <button type="button" disabled={disabled} onClick={() => setAdding(true)} className={primaryClass}>項目を追加</button>
                <MoreMenu disabled={disabled} items={[
                    { label: '月の予算をコピー', onSelect: () => setCopying(true) },
                    { label: 'ゴールから計画を作成', onSelect: () => setPlanning(true) },
                ]} />
            </div>
        </div>
        <GoalContribution check={check.data} error={check.error} currency={currency} disabled={disabled} onCreate={() => setPlanning(true)} />
        <Feedback loading={resource.loading || accounts.loading} error={resource.error || accounts.error || (scheduled.error ? `自動取引の予定を取得できませんでした。${scheduled.error}` : '')} />
        <Feedback error={mutation.error && !adding ? mutation.error : undefined} message={message || mutation.message} />
        {model && <BudgetTable accounts={rows} earmarks={earmarks} currency={currency} narrowed={narrowed}
            highlight={created} disabled={disabled} onAccount={(row) => setOpenAccount(row.key)} onEarmark={(earmark) => setOpenEarmark(earmark.key)} />}
        {accountRow && <AccountOverlay key={accountRow.key} row={accountRow} context={context} onClose={() => setOpenAccount(null)} />}
        {earmarkRow && <EarmarkOverlay key={earmarkRow.key} earmark={earmarkRow} context={context} onClose={() => setOpenEarmark(null)} />}
        {copying && <MonthCopy period={period} clientName={clientName} onBusy={(busy) => { setCopyBusy(busy); onBusy(busy); }} onCopied={(text) => { setCopying(false); setMessage(text); refresh(); }} onClose={() => setCopying(false)} />}
        {planning && <GoalPlanDialog onClose={(applied) => { setPlanning(false); notifications.refresh(); if (applied) refresh(); }} />}
        {adding && <AddItem currency={currency} busy={disabled} error={mutation.error} onSave={add} onClose={() => setAdding(false)} />}
    </div>;
}

export default function Plan() {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const [busy, setBusy] = useState(false);
    const [periodEdit, setPeriod] = useState<string | null>(null);
    const [filters, setFilters] = useState(storedFilters);
    const period = periodEdit ?? clientToday(timezone).slice(0, 7);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const changeFilters = (next: Filters) => {
        setFilters(next);
        // The search is per visit; the scope stays for the next one.
        try { localStorage.setItem(FILTERS_KEY, JSON.stringify({ scope: next.scope })); } catch { /* storage unavailable */ }
    };
    return <section>
        <MonthlyPlan key={`${clientId}:${period}:${currency}`} period={period} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined}
            filters={filters} onFilters={changeFilters} onBusy={setBusy} picker={<MonthPicker value={period} onChange={setPeriod} disabled={busy} />} />
    </section>;
}
