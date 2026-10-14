import type { ReactNode } from 'react';
import { OverlayFooter } from '../../components/Overlay';
import { buttonClass, inputClass, primaryClass } from './forms';

export function Feedback({ loading, error, message }: { loading?: boolean; error?: string; message?: string }) {
    return <>
        {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">読み込んでいます…</p>}
        {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{error}</p>}
        {message && <p role="status" className="text-sm text-[var(--studio-positive)]">{message}</p>}
    </>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
    return <label className="block space-y-2 text-sm"><span className="text-[var(--studio-text-muted)]">{label}</span>{children}</label>;
}

export function Choice({ label, value, options, onChange, required = false }: {
    label: string; value: number | null | undefined;
    options: Array<{ id: number; name: string; is_active?: boolean }>;
    onChange: (value: number | null) => void; required?: boolean;
}) {
    return <Field label={label}>
        <select className={inputClass} value={value ?? ''} required={required} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
            <option value="">未設定</option>
            {/* Keep an existing reference visible even when its lookup is no longer available. */}
            {value != null && !options.some((row) => row.id === value) && <option value={value}>#{value}（一覧にありません）</option>}
            {options.map((row) => <option key={row.id} value={row.id}>{row.name}{row.is_active === false ? '（無効）' : ''}</option>)}
        </select>
    </Field>;
}

export function EditorActions({ busy, form, onCancel }: { busy: boolean; form: string; onCancel: () => void }) {
    const save = <button type="submit" form={form} disabled={busy} className={primaryClass}>{busy ? '保存中…' : '保存'}</button>;
    return <OverlayFooter fallback={<div className="flex justify-end gap-2 md:col-span-2">
        {save}
        <button type="button" disabled={busy} onClick={onCancel} className={buttonClass}>キャンセル</button>
    </div>}>{save}</OverlayFooter>;
}

export function DataTable({ columns, children }: { columns: string[]; children: ReactNode }) {
    return <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
        <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]"><tr>{columns.map((label) => <th key={label} scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{children}</tbody>
        </table>
    </div>;
}

export function RowActions({ name, disabled, onEdit, onDelete, deleteLabel = '削除' }: { name: string; disabled: boolean; onEdit: () => void; onDelete: () => void; deleteLabel?: string }) {
    return <td className="whitespace-nowrap px-5 py-3"><div className="flex gap-2">
        <button type="button" disabled={disabled} onClick={onEdit} aria-label={`${name}を編集`} className={buttonClass}>編集</button>
        <button type="button" disabled={disabled} onClick={onDelete} aria-label={`${name}を${deleteLabel}`} className={`${buttonClass} text-[var(--studio-danger)]`}>{deleteLabel}</button>
    </div></td>;
}
