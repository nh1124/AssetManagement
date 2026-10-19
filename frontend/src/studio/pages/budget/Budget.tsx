import Overlay from '../../components/Overlay';
import { clientToday, useTimezone } from '../../datetime';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { getBudgetSummary, getScheduledTransactions } from '../../../api';
import { getSavingsCheck } from '../../../api/goalBudget';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import AccountEditor from '../db/AccountEditor';
import { buttonClass, inputClass, loadAccounts, primaryClass, useMutation, type DatabaseAccount } from '../db/forms';
import GoalBudgetReflection from '../goals/GoalBudgetReflection';
import GoalReflectionNotice from '../goals/GoalReflectionNotice';
import { GOAL_REFLECTION, useNotifications } from '../../notificationContext';
import MonthPicker from '../ledger/MonthPicker';
import MonthCopy from './MonthCopy';
import SavingsCheck from './SavingsCheck';
import { AccountOverlay, EarmarkOverlay, type OverlayContext } from './BudgetOverlay';
import { SCOPES, buildModel, earmarkMatches, needByName, rowMatches, savingsHeadline, type BudgetSummary, type Scope } from './budgetRows';
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
        <p className="mb-4 text-xs text-[var(--studio-text-muted)]">作成すると予算に「未設定」で並びます。</p>
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

/** The notices in one line: open it for the goal reflection and the savings breakdown. */
function Notices({ check, checkError, currency, reflect }: {
    check: Parameters<typeof SavingsCheck>[0]['check'] | null; checkError: string; currency: string; reflect: ReactNode;
}) {
    const { items } = useNotifications();
    const reflection = items.some((item) => item.kind === GOAL_REFLECTION);
    const issues = [
        ...(check && check.shortfall > 0 ? [`積立が ${formatCurrency(check.shortfall, currency)} 不足`] : []),
        ...(reflection ? ['ゴールの反映待ち'] : []),
        ...(checkError ? ['積立の比較を取得できません'] : []),
    ];
    if (!check && !reflection && !checkError) return null;
    return <details className="text-sm">
        <summary className="cursor-pointer text-xs">
            {issues.length
                ? <span className="text-[var(--studio-warning)]">確認 {issues.length}件：{issues.join('・')}</span>
                : <span className="text-[var(--studio-text-muted)]">{check && savingsHeadline(check, currency)}</span>}
            {check && <span className="ml-2 tabular-nums text-[var(--studio-text-muted)]">予算の積立 {formatCurrency(check.budgeted, currency)} ／ 必要額 {formatCurrency(check.need, currency)}</span>}
        </summary>
        <div className="mt-2 space-y-3">
            <GoalReflectionNotice action={reflect} />
            {checkError ? <Feedback error={`積立と必要額の比較を取得できませんでした。${checkError}`} /> : check && <SavingsCheck check={check} currency={currency} />}
        </div>
    </details>;
}

function MonthlyBudget({ period, currency, clientName, filters, picker, onFilters, onBusy }: {
    period: string; currency: string; clientName?: string; filters: Filters; picker: ReactNode;
    onFilters: (filters: Filters) => void; onBusy: (busy: boolean) => void;
}) {
    const load = useCallback(() => loadSummary(period), [period]);
    const resource = useResource(load);
    const loadCheck = useCallback(() => getSavingsCheck(period), [period]);
    const check = useResource(loadCheck);
    const loadScheduled = useCallback(() => getScheduledTransactions(period), [period]);
    const scheduled = useResource(loadScheduled);
    const accounts = useResource(loadAccounts);
    const refresh = () => { resource.reload(); check.reload(); };
    const mutation = useMutation();
    const notifications = useNotifications();
    const [copyBusy, setCopyBusy] = useState(false);
    const [copying, setCopying] = useState(false);
    const [reflecting, setReflecting] = useState(false);
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
    const need = useMemo(() => needByName(check.data), [check.data]);
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
    const reflect = <button type="button" disabled={disabled} onClick={() => setReflecting(true)} className={buttonClass}>ゴールから更新</button>;

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
                    { label: 'ゴールから更新', onSelect: () => setReflecting(true) },
                ]} />
            </div>
        </div>
        <Notices check={check.data} checkError={check.error} currency={currency} reflect={reflect} />
        <Feedback loading={resource.loading || accounts.loading} error={resource.error || accounts.error || (scheduled.error ? `自動取引の予定を取得できませんでした。${scheduled.error}` : '')} />
        <Feedback error={mutation.error && !adding ? mutation.error : undefined} message={message || mutation.message} />
        {model && <BudgetTable accounts={rows} earmarks={earmarks} currency={currency} narrowed={narrowed} shortfall={check.data?.shortfall ?? 0} need={need}
            highlight={created} disabled={disabled} onAccount={(row) => setOpenAccount(row.key)} onEarmark={(earmark) => setOpenEarmark(earmark.key)} />}
        {accountRow && <AccountOverlay key={accountRow.key} row={accountRow} context={context} onClose={() => setOpenAccount(null)} />}
        {earmarkRow && <EarmarkOverlay key={earmarkRow.key} earmark={earmarkRow} need={need.get(earmarkRow.name)} context={context} onClose={() => setOpenEarmark(null)} />}
        {copying && <MonthCopy period={period} clientName={clientName} onBusy={(busy) => { setCopyBusy(busy); onBusy(busy); }} onCopied={(text) => { setCopying(false); setMessage(text); refresh(); }} onClose={() => setCopying(false)} />}
        {reflecting && <GoalBudgetReflection title="ゴールから予算を更新" initialPeriod={period} onClose={() => { setReflecting(false); notifications.refresh(); }} onApplied={refresh} />}
        {adding && <AddItem currency={currency} busy={disabled} error={mutation.error} onSave={add} onClose={() => setAdding(false)} />}
    </div>;
}

export default function Budget() {
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
        <MonthlyBudget key={`${clientId}:${period}:${currency}`} period={period} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined}
            filters={filters} onFilters={changeFilters} onBusy={setBusy} picker={<MonthPicker value={period} onChange={setPeriod} disabled={busy} />} />
    </section>;
}
