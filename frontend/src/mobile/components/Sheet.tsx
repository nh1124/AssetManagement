import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { focusRing } from './ui';

// Open sheets, newest last: only the topmost answers Escape and keeps focus (a confirmation over an editor).
const open: string[] = [];

/** A bottom sheet: rises over the screen, closes on the backdrop, Escape or the close button
 * (not while busy). Focus moves into it and stays there; it goes back where it was on close. */
export default function Sheet({ title, onClose, children, footer, busy = false, tall = false }: {
    title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; busy?: boolean; tall?: boolean;
}) {
    const heading = useId();
    const self = useId();
    const panel = useRef<HTMLDivElement>(null);
    const close = useRef(onClose);
    const blocked = useRef(busy);
    // The key handler outlives renders; it reads the latest close and busy through these.
    useEffect(() => {
        close.current = onClose;
        blocked.current = busy;
    });
    useEffect(() => {
        open.push(self);
        const previous = document.activeElement as HTMLElement | null;
        panel.current?.focus();
        const onKey = (event: KeyboardEvent) => {
            if (open[open.length - 1] !== self || !panel.current) return;
            if (event.key === 'Escape') {
                if (!blocked.current) close.current();
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = [...panel.current.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
                .filter((element) => !element.hasAttribute('disabled'));
            if (!focusable.length) { event.preventDefault(); return; }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            const inside = focusable.includes(document.activeElement as HTMLElement);
            if (event.shiftKey && (document.activeElement === first || !inside)) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && (document.activeElement === last || !inside)) { event.preventDefault(); first.focus(); }
        };
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('keydown', onKey);
            open.splice(open.indexOf(self), 1);
            previous?.focus?.();
        };
    }, [self]);
    return <div className="fixed inset-0 z-50 flex items-end justify-center">
        <div className="mobile-backdrop absolute inset-0 bg-black/40" aria-hidden onClick={() => { if (!busy) onClose(); }} />
        <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={heading} tabIndex={-1}
            className={`mobile-sheet relative flex w-full max-w-lg flex-col rounded-t-3xl bg-[var(--studio-bg)] shadow-2xl focus:outline-none ${tall ? 'h-[92dvh]' : 'max-h-[92dvh]'}`}>
            <div className="flex justify-center pt-2" aria-hidden><span className="h-1 w-10 rounded-full bg-[var(--studio-border-strong)]" /></div>
            <header className="flex items-center justify-between gap-3 px-5 pb-2 pt-2">
                <h2 id={heading} className="text-base font-semibold">{title}</h2>
                <button type="button" onClick={onClose} disabled={busy} aria-label="閉じる"
                    className={`-mr-2 flex h-11 w-11 items-center justify-center rounded-full text-[var(--studio-text-muted)] active:bg-[var(--studio-accent-soft)] disabled:opacity-40 ${focusRing}`}>
                    <X size={20} aria-hidden />
                </button>
            </header>
            <div className="mobile-scroll min-h-0 flex-1 overflow-y-auto px-5 pb-4">{children}</div>
            {footer && <footer className="border-t border-[var(--studio-border)] bg-[var(--studio-surface)] px-5 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">{footer}</footer>}
            {!footer && <div className="pb-[env(safe-area-inset-bottom)]" />}
        </div>
    </div>;
}
