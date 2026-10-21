import { Settings } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import Overlay from '../../components/Overlay';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { getBudgetSummary, getScheduledTransactions } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import AccountEditor from '../db/AccountEditor';
import { buttonClass, inputClass, loadAccounts, primaryClass, useMutation, type DatabaseAccount } from '../db/forms';
import ReflectionOverlay from './ReflectionOverlay';
import PlanAutomatic from './PlanAutomatic';
import { usePlanMonth } from './planMonth';
import { useNotifications } from '../../notificationContext';
import MonthPicker from '../ledger/MonthPicker';
import MonthCopy from './MonthCopy';
import { AccountOverlay, EarmarkOverlay, type OverlayContext } from './BudgetOverlay';
import { SCOPES, buildModel, earmarkMatches, rowMatches, type BudgetSummary, type Scope } from './budgetRows';
import BudgetTable, { EarmarkTable } from './BudgetTable';

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
    return <Overlay title="項目を追加（口座・勘定科目）" help="作成すると計画に「未設定」で並びます。" onClose={onClose}>
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
        <div role="menu" className="absolute right-0 z-10 mt-1 w-60 rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] py-1 shadow-lg">
            {items.map((item) => <button key={item.label} type="button" role="menuitem" onClick={() => { if (menu.current) menu.current.open = false; item.onSelect(); }}
                className="block w-full px-3 py-2 text-left text-sm hover:bg-[var(--studio-accent-soft)]">{item.label}</button>)}
        </div>
    </details>;
}

export type PlanView = 'plan' | 'earmarks' | 'auto';

function MonthlyPlan({ view, period, currency, clientName, filters, picker, onFilters, onBusy }: {
    view: PlanView; period: string; currency: string; clientName?: string; filters: Filters; picker: ReactNode;
    onFilters: (filters: Filters) => void; onBusy: (busy: boolean) => void;
}) {
    const load = useCallback(() => loadSummary(period), [period]);
    const resource = useResource(load);
    const loadScheduled = useCallback(() => getScheduledTransactions(period), [period]);
    const scheduled = useResource(loadScheduled);
    const accounts = useResource(loadAccounts);
    const refresh = () => resource.reload();
    const mutation = useMutation();
    const notifications = useNotifications();
    const [copyBusy, setCopyBusy] = useState(false);
    const [copying, setCopying] = useState(false);
    // A notification about an automatic run opens the settings with its history (/plan?reflection=history).
    const [search, setSearch] = useSearchParams();
    const [reflecting, setReflecting] = useState(search.has('reflection'));
    useEffect(() => {
        if (search.has('reflection')) setSearch((params) => { params.delete('reflection'); return params; }, { replace: true });
    }, [search, setSearch]);
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
        period, currency, clientName,
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
            {view !== 'auto' && <div className="w-48"><input type="search" aria-label="名前で検索" placeholder="名前で検索" value={filters.query} onChange={(event) => onFilters({ ...filters, query: event.target.value })} className={inputClass} /></div>}
            {view === 'plan' && <div role="group" aria-label="表示する項目" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {SCOPES.map((scope) => <button key={scope.value} type="button" aria-pressed={filters.scope === scope.value} onClick={() => onFilters({ ...filters, scope: scope.value })} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{scope.label}</button>)}
            </div>}
            <div className="ml-auto flex flex-wrap items-center gap-2">
                {view === 'plan' && <>
                    <button type="button" disabled={disabled} onClick={() => setAdding(true)} className={primaryClass}>項目を追加</button>
                    <MoreMenu disabled={disabled} items={[{ label: '月の予算をコピー', onSelect: () => setCopying(true) }]} />
                </>}
                <button type="button" disabled={!clientName} onClick={() => setReflecting(true)} aria-label="計画への反映の設定" title="計画への反映の設定"
                    className={`${buttonClass} inline-flex items-center gap-1.5`}><Settings size={14} aria-hidden="true" />反映</button>
            </div>
        </div>
        <Feedback loading={resource.loading || accounts.loading} error={resource.error || accounts.error || (scheduled.error ? `自動取引の予定を取得できませんでした。${scheduled.error}` : '')} />
        <Feedback error={mutation.error && !adding ? mutation.error : undefined} message={message || mutation.message} />
        {model && view === 'plan' && <BudgetTable accounts={rows} earmarks={earmarks} currency={currency} narrowed={narrowed} showEarmarks={false}
            highlight={created} disabled={disabled} onAccount={(row) => setOpenAccount(row.key)} onEarmark={(earmark) => setOpenEarmark(earmark.key)} />}
        {model && view === 'earmarks' && <EarmarkTable earmarks={earmarks} currency={currency} disabled={disabled} onEarmark={(earmark) => setOpenEarmark(earmark.key)} />}
        {view === 'auto' && scheduled.data && <PlanAutomatic items={scheduled.data.items} currency={currency} accountName={context.accountName} />}
        {accountRow && <AccountOverlay key={accountRow.key} row={accountRow} context={context} onClose={() => setOpenAccount(null)} />}
        {earmarkRow && <EarmarkOverlay key={earmarkRow.key} earmark={earmarkRow} context={context} onClose={() => setOpenEarmark(null)} />}
        {copying && <MonthCopy period={period} clientName={clientName} onBusy={(busy) => { setCopyBusy(busy); onBusy(busy); }} onCopied={(text) => { setCopying(false); setMessage(text); refresh(); }} onClose={() => setCopying(false)} />}
        {reflecting && <ReflectionOverlay clientName={clientName} currency={currency} onClose={(changed) => { setReflecting(false); notifications.refresh(); if (changed) refresh(); }} />}
        {adding && <AddItem currency={currency} busy={disabled} error={mutation.error} onSave={add} onClose={() => setAdding(false)} />}
    </div>;
}

/** 計画: the month's plan by account (計画と実績), its earmarks (取り置き) and its automatic transactions (自動取引). */
export default function Plan({ view = 'plan' }: { view?: PlanView }) {
    const { clientId, currentClient } = useClient();
    const [busy, setBusy] = useState(false);
    const [period, setPeriod] = usePlanMonth();
    const [filters, setFilters] = useState(storedFilters);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const changeFilters = (next: Filters) => {
        setFilters(next);
        // The search is per visit; the scope stays for the next one.
        try { localStorage.setItem(FILTERS_KEY, JSON.stringify({ scope: next.scope })); } catch { /* storage unavailable */ }
    };
    return <section>
        <MonthlyPlan key={`${clientId}:${period}:${currency}`} view={view} period={period} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined}
            filters={filters} onFilters={changeFilters} onBusy={setBusy} picker={<MonthPicker value={period} onChange={setPeriod} disabled={busy} />} />
    </section>;
}
