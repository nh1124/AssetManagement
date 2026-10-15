export default function MonthPicker({ value, onChange, disabled = false }: {
    value: string;
    onChange: (month: string) => void;
    disabled?: boolean;
}) {
    const openPicker = (input: HTMLInputElement) => {
        // Native pickers vary by browser and can reject calls without user activation.
        if (input.disabled || typeof input.showPicker !== 'function') return;
        try { input.showPicker(); } catch { /* Keep manual month entry available. */ }
    };
    return (
        <label className="flex items-center gap-3 text-sm text-[var(--studio-text-muted)]">
            対象月
            <input type="month" required value={value} disabled={disabled} onClick={(event) => openPicker(event.currentTarget)} onFocus={(event) => openPicker(event.currentTarget)} onChange={(event) => {
                // Clearing a required month must not silently request all history.
                if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value)) onChange(event.target.value);
            }} className="rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] px-3 py-2 text-sm text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40" />
        </label>
    );
}
