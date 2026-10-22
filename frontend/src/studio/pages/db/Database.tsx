import { useId, type ReactNode } from 'react';
import { Help, tooltipClass } from '../../components/Help';
import { OverlayFooter } from '../../components/Overlay';

export { Help };
import { buttonClass, inputClass, primaryClass } from './forms';
import { tr } from '../../i18n';

export function Feedback({ loading, error, message }: { loading?: boolean; error?: string; message?: string }) {
    return <>
        {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
        {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{error}</p>}
        {message && <p role="status" className="text-sm text-[var(--studio-positive)]">{message}</p>}
    </>;
}

// buttonClass already sets a text colour, so a danger button needs its own class.
const dangerClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-danger)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';

export function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
    if (!help) return <label className="block space-y-2 text-sm"><span className="text-[var(--studio-text-muted)]">{label}</span>{children}</label>;
    // The help button stays outside the label, so the control's name is the label alone.
    return <div className="space-y-2 text-sm">
        <div className="flex items-center gap-1.5"><span aria-hidden="true" className="text-[var(--studio-text-muted)]">{label}</span><Help label={label} text={help} /></div>
        <label className="block"><span className="sr-only">{label}</span>{children}</label>
    </div>;
}

// Radio options whose descriptions appear on hover or focus; a native option cannot show one.
export function OptionGroup<T extends string>({ label, help, value, options, onChange }: {
    label: string; help?: string; value: T;
    options: Array<{ value: T; label: string; description: string }>; onChange: (value: T) => void;
}) {
    const name = useId();
    return <fieldset className="space-y-2 text-sm">
        <legend className="mb-2 flex items-center gap-1.5 text-[var(--studio-text-muted)]">{label}{help && <Help label={label} text={help} />}</legend>
        <div className="flex flex-wrap gap-2">{options.map((option) => <label key={option.value} className="group/tip relative cursor-pointer rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] has-checked:border-[var(--studio-accent)] has-checked:bg-[var(--studio-accent-soft)] has-checked:text-[var(--studio-accent)] has-focus-visible:ring-2 has-focus-visible:ring-[var(--studio-accent)] has-disabled:cursor-not-allowed has-disabled:opacity-60">
            <input type="radio" name={name} value={option.value} checked={value === option.value} aria-describedby={`${name}-${option.value}`} onChange={() => onChange(option.value)} className="sr-only" />
            {option.label}
            <span role="tooltip" id={`${name}-${option.value}`} className={`${tooltipClass} group-hover/tip:visible group-has-focus-visible/tip:visible`}>{option.description}</span>
        </label>)}</div>
    </fieldset>;
}

export function Choice({ label, help, value, options, onChange, required = false, disabled = false }: {
    label: string; help?: string; value: number | null | undefined;
    options: Array<{ id: number; name: string; is_active?: boolean }>;
    onChange: (value: number | null) => void; required?: boolean; disabled?: boolean;
}) {
    return <Field label={label} help={help}>
        <select className={inputClass} value={value ?? ''} required={required} disabled={disabled} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
            <option value="">{tr('未設定', 'Not set')}</option>
            {/* Keep an existing reference visible even when its lookup is no longer available. */}
            {value != null && !options.some((row) => row.id === value) && <option value={value}>{tr(`#${value}（一覧にありません）`, `#${value} (not in the list)`)}</option>}
            {options.map((row) => <option key={row.id} value={row.id}>{row.name}{row.is_active === false ? tr('（無効）', ' (inactive)') : ''}</option>)}
        </select>
    </Field>;
}

export function EditorActions({ busy, form, onCancel, onDelete }: { busy: boolean; form: string; onCancel: () => void; onDelete?: () => void }) {
    const save = <button type="submit" form={form} disabled={busy} className={primaryClass}>{busy ? tr('保存中…', 'Saving…') : tr('保存', 'Save')}</button>;
    // Deleting sits apart from saving, on the far side and in the danger colour.
    const remove = onDelete && <button type="button" disabled={busy} onClick={onDelete} className={`${dangerClass} mr-auto`}>{tr('削除', 'Delete')}</button>;
    return <OverlayFooter fallback={<div className="flex justify-end gap-2 md:col-span-2">
        {remove}
        {save}
        <button type="button" disabled={busy} onClick={onCancel} className={buttonClass}>{tr('キャンセル', 'Cancel')}</button>
    </div>}>{remove}{save}</OverlayFooter>;
}

export function DataTable({ columns, children }: { columns: string[]; children: ReactNode }) {
    return <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
        <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]"><tr>{columns.map((label) => <th key={label} scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{children}</tbody>
        </table>
    </div>;
}

// A record opens its editor from anywhere on its row; the name is the keyboard target.
export function EditableRow({ disabled, onEdit, className = '', children }: { disabled: boolean; onEdit: () => void; className?: string; children: ReactNode }) {
    return <tr onClick={() => { if (!disabled) onEdit(); }} className={`${className} ${disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}`}>{children}</tr>;
}

export function RowTitle({ name, disabled, onEdit, children }: { name: string; disabled: boolean; onEdit: () => void; children: ReactNode }) {
    return <th scope="row" className="px-5 py-3 font-medium">
        <button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={tr(`${name}を編集`, `Edit ${name}`)} onClick={(event) => { event.stopPropagation(); onEdit(); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:cursor-default">{children}</button>
    </th>;
}

export function ActiveSwitch({ name, active, disabled, busy = false, onToggle }: { name: string; active: boolean; disabled: boolean; busy?: boolean; onToggle: () => void }) {
    return <button type="button" role="switch" aria-checked={active} aria-label={tr(`${name}の有効状態`, `${name} active`)} disabled={disabled} onClick={(event) => { event.stopPropagation(); onToggle(); }} className="flex items-center gap-2 whitespace-nowrap rounded-md px-1 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:cursor-not-allowed">
        <span aria-hidden="true" className={`flex h-5 w-9 items-center rounded-full px-0.5 ${active ? 'justify-end bg-[var(--studio-accent)]' : 'justify-start bg-[var(--studio-border-strong)]'}`}><span className="h-4 w-4 rounded-full bg-[var(--studio-surface)]" /></span>
        <span>{active ? tr('有効', 'Active') : tr('無効', 'Inactive')}</span>
        {busy && <span className="text-[var(--studio-text-muted)]">{tr('更新中…', 'Updating…')}</span>}
    </button>;
}

export function RowActions({ name, disabled, onEdit, onDelete, deleteLabel = tr('削除', 'Delete') }: { name: string; disabled: boolean; onEdit: () => void; onDelete: () => void; deleteLabel?: string }) {
    return <td className="whitespace-nowrap px-5 py-3"><div className="flex gap-2">
        <button type="button" disabled={disabled} onClick={onEdit} aria-label={tr(`${name}を編集`, `Edit ${name}`)} className={buttonClass}>{tr('編集', 'Edit')}</button>
        <button type="button" disabled={disabled} onClick={onDelete} aria-label={tr(`${name}を${deleteLabel}`, `${deleteLabel} ${name}`)} className={dangerClass}>{deleteLabel}</button>
    </div></td>;
}
