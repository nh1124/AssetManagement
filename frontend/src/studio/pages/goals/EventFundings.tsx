import { useId, useState, type FormEvent } from 'react';
import type { LifeEvent, LifeEventKind } from '../../../types';
import { formatDate } from '../../datetime';
import { DataTable, EditorActions, Feedback } from '../db/Database';
import { buttonClass, inputClass, type DatabaseAccount } from '../db/forms';
import { eventAmount, FUNDING_LABELS, KIND_LABELS } from './eventKinds';

const HELP: Record<LifeEventKind, string> = {
    expense: '目標日にこの口座から払います。計画の作成では、割合に応じた額をイベントと同じ名前の取り置き（ゴール）として各口座に積み立てます。',
    income: '目標日にこの口座へ入ります。',
    borrowing: '借りたお金がこの口座へ入り、同じ額の借入（負債）ができます。',
    repayment: '毎月の返済をこの口座から払います。',
};

const total = (event: LifeEvent) => event.fundings.reduce((sum, row) => sum + row.share, 0);
const shareText = (value: number) => `${Number(value.toFixed(2))}%`;

/** ライフイベントの資金: per event, the accounts that pay it (or receive it) and their shares. */
export function EventFundingTable({ events, currency, disabled, onEdit }: {
    events: LifeEvent[]; currency: string; disabled: boolean; onEdit: (event: LifeEvent) => void;
}) {
    const rows = [...events].sort((a, b) => a.target_date.localeCompare(b.target_date) || a.id - b.id);
    if (!rows.length) return <p className="rounded-md border border-dashed border-[var(--studio-border)] p-4 text-sm text-[var(--studio-text-muted)]">ライフイベントがありません。「ライフイベント」で追加してください。</p>;
    return <DataTable columns={['ライフイベント', '種別', '日付', '金額', '口座と割合']}>
        {rows.map((event) => {
            const rest = 100 - total(event);
            return <tr key={event.id} onClick={() => { if (!disabled) onEdit(event); }} className={disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'}>
                <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">
                    <button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={`${event.name}の口座を編集`} onClick={(click) => { click.stopPropagation(); onEdit(event); }}
                        className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{event.name}</button>
                </th>
                <td className="whitespace-nowrap px-5 py-3">{KIND_LABELS[event.direction]}</td>
                <td className="whitespace-nowrap px-5 py-3">{formatDate(event.target_date)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{eventAmount(event, currency)}</td>
                <td className="px-5 py-3">{event.fundings.length
                    ? <span className="tabular-nums">{event.fundings.map((row) => `${row.account_name ?? `#${row.account_id}`} ${shareText(row.share)}`).join('・')}
                        {rest > 0.005 && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">残り {shareText(rest)} は残りの純資産</span>}</span>
                    : <span className="text-xs text-[var(--studio-text-muted)]">未設定（残りの純資産）</span>}</td>
            </tr>;
        })}
    </DataTable>;
}

interface Row { key: number; accountId: number | null; share: string }

/** The accounts of one event and their shares in percent, at most 100% in total. */
export function EventFundingEditor({ event, accounts, busy, onSave, onCancel }: {
    event: LifeEvent; accounts: DatabaseAccount[]; busy: boolean;
    onSave: (fundings: Array<{ account_id: number; share: number }>) => void; onCancel: () => void;
}) {
    const form = useId();
    const [rows, setRows] = useState<Row[]>(() => event.fundings.length
        ? event.fundings.map((row, index) => ({ key: index, accountId: row.account_id, share: String(row.share) }))
        : [{ key: 0, accountId: null, share: '100' }]);
    const [error, setError] = useState('');
    const chosen = new Set(rows.map((row) => row.accountId));
    const assets = accounts.filter((row) => row.account_type === 'asset' && (row.is_active || chosen.has(row.id)));
    const sum = rows.reduce((value, row) => value + (Number(row.share) || 0), 0);
    const change = (key: number, patch: Partial<Row>) => setRows(rows.map((row) => row.key === key ? { ...row, ...patch } : row));
    const submit = (submitted: FormEvent<HTMLFormElement>) => {
        submitted.preventDefault();
        if (busy) return;
        const filled = rows.filter((row) => row.accountId != null || row.share.trim() !== '');
        if (filled.some((row) => row.accountId == null || !(Number(row.share) > 0))) {
            setError('口座を選び、割合は0より大きい数値で入力してください。');
            return;
        }
        if (new Set(filled.map((row) => row.accountId)).size !== filled.length) {
            setError('同じ口座は一度だけ選んでください。');
            return;
        }
        if (filled.reduce((value, row) => value + Number(row.share), 0) > 100.0001) {
            setError('割合の合計は100%以下にしてください。');
            return;
        }
        setError('');
        onSave(filled.map((row) => ({ account_id: row.accountId as number, share: Number(row.share) })));
    };
    return <form id={form} onSubmit={submit} className="space-y-4">
        <p className="text-sm">{KIND_LABELS[event.direction]}・{formatDate(event.target_date)}</p>
        <p className="text-xs text-[var(--studio-text-muted)]">{HELP[event.direction]}割合の合計が100%に満たない分は、残りの純資産から払います（受け取ります）。選んだ口座はシミュレーションの使用口座になります。</p>
        <Feedback error={error} />
        <fieldset disabled={busy} className="space-y-2">
            <div className="grid grid-cols-[1fr_7rem_auto] gap-2 text-xs text-[var(--studio-text-muted)]"><span>{FUNDING_LABELS[event.direction]}</span><span>割合（%）</span><span /></div>
            {rows.map((row) => <div key={row.key} className="grid grid-cols-[1fr_7rem_auto] items-center gap-2">
                <select aria-label={FUNDING_LABELS[event.direction]} value={row.accountId ?? ''} onChange={(changed) => change(row.key, { accountId: changed.target.value ? Number(changed.target.value) : null })} className={inputClass}>
                    <option value="">口座を選ぶ</option>
                    {assets.map((account) => <option key={account.id} value={account.id}>{account.name}{account.is_active ? '' : '（無効）'}</option>)}
                </select>
                <input aria-label="割合（%）" inputMode="decimal" value={row.share} onChange={(changed) => change(row.key, { share: changed.target.value })} className={inputClass} />
                <button type="button" onClick={() => setRows(rows.filter((item) => item.key !== row.key))} className={`${buttonClass} text-[var(--studio-danger)]`}>外す</button>
            </div>)}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <button type="button" onClick={() => setRows([...rows, { key: Math.max(-1, ...rows.map((row) => row.key)) + 1, accountId: null, share: String(Math.max(0, 100 - sum)) }])} className={buttonClass}>口座を追加</button>
                <span className={`text-xs tabular-nums ${sum > 100.0001 ? 'text-[var(--studio-danger)]' : 'text-[var(--studio-text-muted)]'}`}>合計 {shareText(sum)}</span>
            </div>
            <EditorActions form={form} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}
