import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatCurrency } from '../../utils/currency';

/** Shared look of the mobile screens: cards on the warm background, amounts in tabular figures. */
export const primaryButton = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[var(--studio-accent)] px-4 text-sm font-semibold text-[var(--studio-accent-text)] active:opacity-80 disabled:opacity-40';
export const secondaryButton = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-[var(--studio-border)] bg-[var(--studio-surface)] px-4 text-sm font-medium text-[var(--studio-text)] active:bg-[var(--studio-accent-soft)] disabled:opacity-40';
export const dangerButton = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-[var(--studio-danger)] px-4 text-sm font-medium text-[var(--studio-danger)] active:bg-red-50 disabled:opacity-40';
export const fieldClass = 'block w-full min-h-11 rounded-xl border border-[var(--studio-border)] bg-[var(--studio-surface)] px-3 text-base text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
export const focusRing = 'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--studio-accent)]';

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
    return <section className={`rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)] ${className}`}>{children}</section>;
}

/** A card's heading, with an optional link to the screen that has the rest. */
export function CardTitle({ children, to, action }: { children: ReactNode; to?: string; action?: string }) {
    return <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-[var(--studio-text)]">{children}</h2>
        {to && <Link to={to} className={`-mr-1 flex min-h-11 items-center gap-0.5 rounded px-1 text-xs font-medium text-[var(--studio-accent)] ${focusRing}`}>{action ?? 'すべて'}<ChevronRight size={14} aria-hidden /></Link>}
    </div>;
}

export function Money({ value, currency, className = '', signed = false }: { value: number; currency: string; className?: string; signed?: boolean }) {
    const text = formatCurrency(Math.abs(value), currency);
    return <span className={`tabular-nums ${className}`}>{signed ? (value < 0 ? '−' : value > 0 ? '+' : '') : value < 0 ? '−' : ''}{text}</span>;
}

/** How much of a budget is used: green while within it, red past it. */
export function ProgressBar({ value, max, tone, label }: { value: number; max: number; tone?: 'accent' | 'positive' | 'danger'; label: string }) {
    const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : value > 0 ? 1 : 0;
    const over = max > 0 && value > max;
    const color = tone === 'danger' || over ? 'bg-[var(--studio-danger)]' : tone === 'positive' ? 'bg-[var(--studio-positive)]' : 'bg-[var(--studio-accent)]';
    return <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio * 100)}
        className="h-2 w-full overflow-hidden rounded-full bg-[var(--studio-accent-soft)]">
        <div className={`h-full rounded-full ${color} transition-[width] duration-500`} style={{ width: `${ratio * 100}%` }} />
    </div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
    return <div role="status" aria-label="読み込んでいます" className="space-y-3">
        {Array.from({ length: lines }, (_, index) => <div key={index} className="h-16 animate-pulse rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]" />)}
    </div>;
}

export function Empty({ icon, title, body, children }: { icon?: ReactNode; title: string; body?: string; children?: ReactNode }) {
    return <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-[var(--studio-border-strong)] px-6 py-10 text-center">
        {icon && <div className="text-[var(--studio-text-faint)]">{icon}</div>}
        <p className="text-sm font-medium">{title}</p>
        {body && <p className="text-xs text-[var(--studio-text-muted)]">{body}</p>}
        {children}
    </div>;
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
    return <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl bg-red-50 px-4 py-3 text-sm text-[var(--studio-danger)]">
        <span>{message}</span>
        {onRetry && <button type="button" onClick={onRetry} className={`shrink-0 rounded-lg px-2 py-1 font-medium underline ${focusRing}`}>再読み込み</button>}
    </div>;
}

/** A row in a list card: a title, a line under it, and what is on the right. Whole row taps when given an action. */
export function Row({ title, subtitle, trailing, onClick, to, chevron = Boolean(onClick || to) }: {
    title: ReactNode; subtitle?: ReactNode; trailing?: ReactNode; onClick?: () => void; to?: string; chevron?: boolean;
}) {
    const body = <>
        <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{title}</div>
            {subtitle && <div className="mt-0.5 truncate text-xs text-[var(--studio-text-muted)]">{subtitle}</div>}
        </div>
        {trailing && <div className="shrink-0 text-right text-sm">{trailing}</div>}
        {chevron && <ChevronRight size={16} className="shrink-0 text-[var(--studio-text-faint)]" aria-hidden />}
    </>;
    const classes = `flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left ${focusRing}`;
    if (to) return <Link to={to} className={`${classes} active:bg-[var(--studio-accent-soft)]`}>{body}</Link>;
    if (onClick) return <button type="button" onClick={onClick} className={`${classes} active:bg-[var(--studio-accent-soft)]`}>{body}</button>;
    return <div className={classes}>{body}</div>;
}

/** Rows grouped in one card, divided by hairlines. */
export function List({ children, title }: { children: ReactNode; title?: string }) {
    return <section>
        {title && <h2 className="mb-2 px-1 text-xs font-semibold tracking-wide text-[var(--studio-text-muted)]">{title}</h2>}
        <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">{children}</div>
    </section>;
}

/** Two to four choices in one pill, like the iOS segmented control; arrow keys move between them. */
export function Segmented<T extends string>({ value, options, onChange, label }: {
    value: T; options: Array<{ value: T; label: string }>; onChange: (value: T) => void; label: string;
}) {
    const group = useRef<HTMLDivElement>(null);
    const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
        const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        const next = (options.findIndex((option) => option.value === value) + step + options.length) % options.length;
        onChange(options[next].value);
        group.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus();
    };
    return <div ref={group} role="radiogroup" aria-label={label} onKeyDown={onKey} className="grid rounded-xl bg-[var(--studio-accent-soft)] p-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
        {options.map((option) => <button key={option.value} type="button" role="radio" aria-checked={value === option.value} tabIndex={value === option.value ? 0 : -1} onClick={() => onChange(option.value)}
            className={`min-h-10 rounded-lg text-sm font-medium transition-colors ${focusRing} ${value === option.value ? 'bg-[var(--studio-surface)] text-[var(--studio-accent)] shadow-sm' : 'text-[var(--studio-text-muted)]'}`}>
            {option.label}
        </button>)}
    </div>;
}

export function Badge({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'accent' | 'warning' | 'danger' }) {
    const colors = { muted: 'bg-[var(--studio-bg)] text-[var(--studio-text-muted)]', accent: 'bg-[var(--studio-accent-soft)] text-[var(--studio-accent)]',
        warning: 'bg-amber-50 text-[var(--studio-warning)]', danger: 'bg-red-50 text-[var(--studio-danger)]' }[tone];
    return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${colors}`}>{children}</span>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
    return <label className="block space-y-1.5">
        <span className="text-xs font-medium text-[var(--studio-text-muted)]">{label}</span>
        {children}
        {hint && <span className="block text-xs text-[var(--studio-text-faint)]">{hint}</span>}
    </label>;
}
