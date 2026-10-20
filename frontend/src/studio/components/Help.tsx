import { useId } from 'react';

const tooltipBase = 'pointer-events-none invisible absolute z-10 rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] p-2 text-xs font-normal leading-relaxed text-[var(--studio-text)] shadow-lg';

// Above the control: the overlay body clips what hangs below its last field.
export const tooltipClass = `${tooltipBase} bottom-full left-0 mb-1 w-64`;

/** A short explanation beside a field name or a heading, shown on hover or keyboard focus.
 * below: for headings at the top of a panel or dialog, where above would be clipped;
 * end: for icons near the right edge; wide: for explanations longer than a sentence or two. */
export function Help({ label, text, below = false, end = false, wide = false }: {
    label: string; text: string; below?: boolean; end?: boolean; wide?: boolean;
}) {
    const id = useId();
    const place = `${below ? 'top-full mt-1' : 'bottom-full mb-1'} ${end ? 'right-0' : 'left-0'} ${wide ? 'w-80' : 'w-64'}`;
    return <span className="group/tip relative inline-flex align-middle">
        <button type="button" aria-label={`${label}の説明`} aria-describedby={id} className="flex h-4 w-4 items-center justify-center rounded-full border border-[var(--studio-border-strong)] text-[10px] font-normal leading-none text-[var(--studio-text-muted)] hover:text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">?</button>
        <span role="tooltip" id={id} className={`${tooltipBase} ${place} group-hover/tip:visible group-focus-within/tip:visible`}>{text}</span>
    </span>;
}
