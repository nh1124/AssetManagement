import { useId, useState, type FormEvent } from 'react';
import { Trash2 } from 'lucide-react';
import { setGoalEarmarks } from '../../../api';
import type { Capsule, GoalEarmarkLink, LifeEventProgress } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { EditorActions, Feedback } from '../db/Database';
import { buttonClass, inputClass } from '../db/forms';

type Row = { key: number; capsule_id: number | null; share: string };

/** 実績管理の設定 for one goal event: which earmarks count toward it, and what percent of each. */
export default function GoalEarmarkEditor({ event, capsules, currency, busy, onSave, onCancel }: {
    event: LifeEventProgress; capsules: Capsule[]; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const form = useId();
    const [rows, setRows] = useState<Row[]>(() => event.earmarks.map((link, index) => ({ key: index, capsule_id: link.capsule_id, share: String(link.share) })));
    const [error, setError] = useState('');
    const update = (key: number, patch: Partial<Row>) => setRows((current) => current.map((row) => row.key === key ? { ...row, ...patch } : row));
    const submit = (submitted: FormEvent<HTMLFormElement>) => {
        submitted.preventDefault();
        if (busy) return;
        const links: GoalEarmarkLink[] = [];
        for (const row of rows) {
            const share = Number(row.share);
            if (row.capsule_id === null || !Number.isFinite(share) || share < 0 || share > 100) { setError('取り置きを選び、割合を0〜100%で入力してください。'); return; }
            if (links.some((link) => link.capsule_id === row.capsule_id)) { setError('同じ取り置きは一度だけ選べます。'); return; }
            links.push({ capsule_id: row.capsule_id, share });
        }
        setError('');
        onSave(() => setGoalEarmarks(event.id, links));
    };
    return <form id={form} onSubmit={submit} className="space-y-4">
        <p className="text-sm text-[var(--studio-text-muted)]">目標額 {formatCurrency(event.target_amount, currency)}・目標日 {event.target_date}。取り置きの確保額 × 割合 の合計を、このイベントの確保額として数えます。</p>
        <Feedback error={error} />
        <fieldset disabled={busy} className="space-y-3">
            {rows.map((row) => <div key={row.key} className="grid grid-cols-[1fr_8rem_auto] items-center gap-2">
                <select aria-label="取り置き" required value={row.capsule_id ?? ''} onChange={(changed) => update(row.key, { capsule_id: changed.target.value ? Number(changed.target.value) : null })} className={inputClass}>
                    <option value="">取り置きを選択</option>
                    {capsules.map((capsule) => <option key={capsule.id} value={capsule.id}>{capsule.name}（確保額 {formatCurrency(capsule.current_balance, currency)}）</option>)}
                </select>
                <label className="flex items-center gap-1 text-sm"><input aria-label="割合（%）" type="number" min="0" max="100" step="any" required value={row.share} onChange={(changed) => update(row.key, { share: changed.target.value })} className={inputClass} />%</label>
                <button type="button" aria-label="この取り置きを外す" onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))} className={buttonClass}><Trash2 size={14} aria-hidden="true" /></button>
            </div>)}
            {rows.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">紐づく取り置きはありません。</p>}
            <button type="button" onClick={() => setRows((current) => [...current, { key: Math.max(0, ...current.map((row) => row.key)) + 1, capsule_id: null, share: '100' }])} className={buttonClass}>取り置きを追加</button>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} />
    </form>;
}
