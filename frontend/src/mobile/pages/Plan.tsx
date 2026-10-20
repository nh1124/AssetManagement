import { useCallback, useState } from 'react';
import { Flag, Plus } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { addPlanRecord, amendPlanRecord, deletePlanRecord, getAccountMonth, type AccountMonth, type PlanRecord, type PlanSection } from '../../api/plan';
import { useClient } from '../../context/ClientContext';
import { formatCurrency } from '../../utils/currency';
import { useConfirm } from '../../studio/components/useConfirm';
import { clientToday, useTimezone } from '../../studio/datetime';
import { KIND_LABELS, TYPE_LABELS, type AccountKind, type AccountRow, type Cell } from '../../studio/pages/plan/budgetRows';
import { assetErrorMessage, useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import MonthSwitcher from '../components/MonthSwitcher';
import { monthLabel, monthParam } from '../months';
import { useRecording } from '../components/recording';
import Sheet from '../components/Sheet';
import { useSnack } from '../components/snack';
import { Badge, Card, Empty, ErrorNote, fieldClass, focusRing, Money, primaryButton, ProgressBar, Segmented, Skeleton } from '../components/ui';
import { loadMonth, totals } from '../data';

const KINDS: AccountKind[] = ['expense', 'income', 'asset', 'liability'];

/** One movement of an account row: actual against budget, and a bar for spending. */
function CellLine({ cell, currency, kind }: { cell: Cell; currency: string; kind: AccountKind | null }) {
    return <div className="space-y-1">
        <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="text-[var(--studio-text-muted)]">{kind === 'expense' || kind === 'income' ? '実績 / 予算' : TYPE_LABELS[cell.type]}</span>
            <span className="tabular-nums">
                <span className="font-semibold text-[var(--studio-text)]">{formatCurrency(cell.actual, currency)}</span>
                <span className="text-[var(--studio-text-muted)]"> / {cell.set ? formatCurrency(cell.budget, currency) : '未設定'}</span>
            </span>
        </div>
        {cell.type === 'expense' && cell.set && <ProgressBar label={`${TYPE_LABELS[cell.type]}の消化`} value={cell.actual} max={cell.budget} />}
    </div>;
}

/** A record in the account sheet; the user's own can be changed or removed. */
function RecordLine({ record, currency, busy, onSave, onDelete }: {
    record: PlanRecord; currency: string; busy: boolean; onSave: (amount: number) => void; onDelete: () => void;
}) {
    const [editing, setEditing] = useState(false);
    const [amount, setAmount] = useState(String(record.amount));
    if (!editing) return <button type="button" disabled={!record.editable || busy} onClick={() => setEditing(true)}
        className={`flex min-h-12 w-full items-center gap-3 px-4 py-2 text-left disabled:cursor-default ${record.editable ? 'active:bg-[var(--studio-accent-soft)]' : ''} ${focusRing}`}>
        <span className="min-w-0 flex-1">
            <span className="block truncate text-sm">{record.name}</span>
            <span className="text-xs text-[var(--studio-text-muted)]">{record.origin_label}{record.editable ? '・タップで変更' : ''}</span>
        </span>
        <Money value={record.amount} currency={currency} className="text-sm font-semibold" />
    </button>;
    return <form className="flex items-center gap-2 px-4 py-2" onSubmit={(event) => { event.preventDefault(); if (Number(amount) >= 0) { onSave(Number(amount)); setEditing(false); } }}>
        <input inputMode="decimal" autoFocus value={amount} aria-label={`${record.name}の金額`} onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ''))} className={`${fieldClass} flex-1`} />
        <button type="submit" disabled={busy} className={`${primaryButton} px-3`}>保存</button>
        <button type="button" disabled={busy} onClick={onDelete} className={`min-h-11 rounded-xl px-2 text-xs font-medium text-[var(--studio-danger)] ${focusRing}`}>削除</button>
    </form>;
}

function SectionCard({ section, currency, busy, onAdd, onSave, onDelete }: {
    section: PlanSection; currency: string; busy: boolean;
    onAdd: (amount: number) => Promise<boolean>; onSave: (record: PlanRecord, amount: number) => void; onDelete: (record: PlanRecord) => void;
}) {
    const [adding, setAdding] = useState('');
    return <section className="overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
        <header className="flex items-baseline justify-between gap-2 px-4 pb-1 pt-3">
            <h3 className="text-sm font-semibold">{section.label}</h3>
            <span className="text-xs tabular-nums text-[var(--studio-text-muted)]">実績 {formatCurrency(section.actual, currency)} / 予算 {formatCurrency(section.total, currency)}</span>
        </header>
        <div className="divide-y divide-[var(--studio-border)]">
            {section.records.map((record, index) => <RecordLine key={record.id ?? `${record.origin}-${index}`} record={record} currency={currency} busy={busy}
                onSave={(amount) => onSave(record, amount)} onDelete={() => onDelete(record)} />)}
            {section.records.length === 0 && <p className="px-4 py-3 text-xs text-[var(--studio-text-muted)]">レコードはありません。</p>}
            {section.can_add && <form className="flex items-center gap-2 px-4 py-2" onSubmit={(event) => {
                event.preventDefault();
                // The amount stays in the field when saving fails.
                if (Number(adding) > 0) void onAdd(Number(adding)).then((saved) => { if (saved) setAdding(''); });
            }}>
                <input inputMode="decimal" value={adding} placeholder="予算を追加（金額）" aria-label={`${section.label}に予算を追加`} onChange={(event) => setAdding(event.target.value.replace(/[^\d.]/g, ''))} className={`${fieldClass} flex-1`} />
                <button type="submit" disabled={busy || !(Number(adding) > 0)} aria-label="追加" className={`${primaryButton} w-11 px-0`}><Plus size={18} aria-hidden /></button>
            </form>}
        </div>
    </section>;
}

/** An account's month: each section's records (the user's are editable), the earmarks it funds, its automatic transactions. */
function AccountSheet({ period, row, currency, onClose }: { period: string; row: AccountRow; currency: string; onClose: (changed: boolean) => void }) {
    const confirm = useConfirm();
    const snack = useSnack();
    const load = useCallback(() => getAccountMonth(period, row.accountId as number), [period, row.accountId]);
    const resource = useResource(load);
    const [busy, setBusy] = useState(false);
    const [changed, setChanged] = useState(false);
    const run = async (action: () => Promise<AccountMonth>, message: string): Promise<boolean> => {
        setBusy(true);
        try {
            resource.setData(await action());
            setChanged(true);
            snack(message);
            return true;
        } catch (failure) {
            snack(assetErrorMessage(failure), 'error');
            return false;
        } finally {
            setBusy(false);
        }
    };
    const data = resource.data;
    return <Sheet title={`${row.name}・${monthLabel(period)}`} onClose={() => onClose(changed)} busy={busy} tall>
        <div className="space-y-4">
            {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
            {!data && !resource.error && <Skeleton lines={2} />}
            {data && data.sections.map((section) => <SectionCard key={section.key} section={section} currency={currency} busy={busy}
                onAdd={(amount) => run(() => addPlanRecord({ period, account_id: data.account.id, section: section.key, amount }), '予算を追加しました')}
                onSave={(record, amount) => { if (record.id !== null) void run(() => amendPlanRecord(record.id as number, { amount }), '予算を変更しました'); }}
                onDelete={(record) => void (async () => {
                    if (record.id !== null && await confirm(`「${record.name}」の予算を削除します。`, '削除する')) await run(() => deletePlanRecord(record.id as number), '予算を削除しました');
                })()} />)}
            {data && data.earmarks.length > 0 && <section className="rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <h3 className="mb-2 text-sm font-semibold">この口座の取り置き</h3>
                <ul className="space-y-1.5 text-sm">{data.earmarks.map((earmark) => <li key={`${earmark.capsule_id}-${earmark.name}`} className="flex justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5"><span className="truncate">{earmark.name}</span>{earmark.goal && <Badge tone="accent">ゴール</Badge>}</span>
                    <Money value={earmark.amount} currency={currency} /></li>)}</ul>
            </section>}
            {data && data.scheduled.length > 0 && <section className="rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <h3 className="mb-2 text-sm font-semibold">今月の自動取引</h3>
                <ul className="space-y-1.5 text-sm">{data.scheduled.map((item, index) => <li key={`${item.name}-${index}`} className="flex justify-between gap-2">
                    <span className="truncate">{item.name}</span><Money value={item.amount} currency={currency} /></li>)}</ul>
            </section>}
            <p className="text-xs text-[var(--studio-text-muted)]">変えられるのは自分で入れた予算です。ゴール・自動取引・カード請求の分は、それぞれの設定（PC版）で変えます。</p>
        </div>
    </Sheet>;
}

/** The month's plan: what is planned and what happened, account by account. */
export default function Plan() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const current = clientToday(timezone).slice(0, 7);
    const [params, setParams] = useSearchParams();
    const period = monthParam(params.get('month'), current);
    const { changed } = useRecording();
    // The tab lives in the URL with the month, so it survives the reload after an edit.
    const kind = (KINDS as string[]).includes(params.get('kind') ?? '') ? params.get('kind') as AccountKind : 'expense';
    const [opened, setOpened] = useState<AccountRow | null>(null);
    const load = useCallback(() => loadMonth(period), [period]);
    const resource = useResource(load);
    // A month still loading never shows the previous month's plan.
    const model = resource.data?.summary.period === period ? resource.data.model : undefined;
    const setParam = (key: 'month' | 'kind', value: string) => {
        const next = new URLSearchParams(params);
        if ((key === 'month' && value === current) || (key === 'kind' && value === 'expense')) next.delete(key); else next.set(key, value);
        setParams(next, { replace: true });
    };
    const spending = model ? totals(model, 'expense') : null;
    const income = model ? totals(model, 'income') : null;
    const rows = model?.accounts.filter((row) => row.kind === kind && row.cells.some((cell) => cell.set || cell.actual !== 0)) ?? [];
    const earmarks = kind === 'asset' ? model?.earmarks.filter((earmark) => earmark.budget !== 0 || earmark.held !== 0) ?? [] : [];
    return <Screen title="計画" top>
        <MonthSwitcher period={period} current={current} onChange={(next) => setParam('month', next)} />
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!model && !resource.error && <Skeleton lines={3} />}
        {spending && income && <Card>
            <div className="grid grid-cols-2 gap-4">
                <div><p className="text-xs text-[var(--studio-text-muted)]">支出</p><Money value={spending.actual} currency={currency} className="text-xl font-bold" />
                    <p className="text-xs text-[var(--studio-text-muted)]">予算 {formatCurrency(spending.budget, currency)}</p></div>
                <div><p className="text-xs text-[var(--studio-text-muted)]">収入</p><Money value={income.actual} currency={currency} className="text-xl font-bold text-[var(--studio-positive)]" />
                    <p className="text-xs text-[var(--studio-text-muted)]">予算 {formatCurrency(income.budget, currency)}</p></div>
            </div>
            <div className="mt-3"><ProgressBar label="支出の予算の消化" value={spending.actual} max={spending.budget} /></div>
        </Card>}
        {model && <>
            <Segmented label="口座・科目の種類" value={kind} onChange={(next) => setParam('kind', next)} options={KINDS.map((value) => ({ value, label: KIND_LABELS[value] }))} />
            {rows.length ? <div className="space-y-2">{rows.map((row) => <button key={row.key} type="button" disabled={row.accountId === null} onClick={() => setOpened(row)}
                className={`w-full space-y-2 rounded-2xl bg-[var(--studio-surface)] p-4 text-left shadow-[var(--mobile-shadow)] active:bg-[var(--studio-accent-soft)] ${focusRing}`}>
                <div className="flex items-center gap-2"><span className="truncate text-sm font-semibold">{row.name}</span>{row.goal && <Badge tone="accent"><Flag size={10} className="mr-0.5" aria-hidden />ゴール</Badge>}</div>
                {row.cells.filter((cell) => cell.set || cell.actual !== 0).map((cell) => <CellLine key={cell.type} cell={cell} currency={currency} kind={row.kind} />)}
            </button>)}</div> : <Empty title={`${KIND_LABELS[kind]}の予算・実績はありません`} body="PC版の計画で口座・科目を追加できます。" />}
            {earmarks.length > 0 && <section className="space-y-2">
                <h2 className="px-1 text-xs font-semibold text-[var(--studio-text-muted)]">取り置き</h2>
                <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
                    {earmarks.map((earmark) => <div key={earmark.key} className="flex items-center gap-3 px-4 py-3">
                        <div className="min-w-0 flex-1"><p className="flex items-center gap-1.5 text-sm font-medium"><span className="truncate">{earmark.name}</span>{earmark.goal && <Badge tone="accent">ゴール</Badge>}</p>
                            <p className="truncate text-xs text-[var(--studio-text-muted)]">{earmark.sources.join('・')}</p></div>
                        <div className="text-right text-xs"><p className="text-sm font-semibold tabular-nums">{formatCurrency(earmark.budget, currency)}</p><p className="text-[var(--studio-text-muted)]">確保額 {formatCurrency(earmark.held, currency)}</p></div>
                    </div>)}
                </div>
            </section>}
        </>}
        {opened && <AccountSheet period={period} row={opened} currency={currency} onClose={(edited) => { setOpened(null); if (edited) changed(); }} />}
    </Screen>;
}
