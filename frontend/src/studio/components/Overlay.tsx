import { Help } from './Help';
import { useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { OverlayFooterContext, OverlayHeaderContext } from './overlayContext';

export function OverlayFooter({ children, fallback }: { children: ReactNode; fallback?: ReactNode }) {
    const host = useContext(OverlayFooterContext);
    // Portalling actions keeps their form's validation and busy state with the editor.
    if (host === undefined) return fallback ?? children;
    return host ? createPortal(children, host) : null;
}

/** Lets an editor rendered inside an Overlay put a control (the active switch) beside the × button. */
export function OverlayHeaderAction({ children }: { children: ReactNode }) {
    const host = useContext(OverlayHeaderContext);
    if (host === undefined) return children;
    return host ? createPortal(children, host) : null;
}

let scrollLocks = 0;
let lockedScrollers: Array<{ element: HTMLElement; overflow: string }> = [];

function lockPage() {
    // The studio scrolls its main element, so locking only the document is insufficient.
    if (scrollLocks++ === 0) {
        lockedScrollers = [document.body, ...document.querySelectorAll<HTMLElement>('.studio-root main')]
            .map((element) => ({ element, overflow: element.style.overflow }));
        for (const { element } of lockedScrollers) element.style.overflow = 'hidden';
    }
    return () => {
        if (--scrollLocks === 0) {
            for (const { element, overflow } of lockedScrollers) element.style.overflow = overflow;
            lockedScrollers = [];
        }
    };
}

export default function Overlay({ title, help, children, footer, headerAction, describedBy, busy = false, onClose }: {
    title: string; help?: string; children: ReactNode; footer?: ReactNode; headerAction?: ReactNode; describedBy?: string; busy?: boolean; onClose: () => void;
}) {
    const titleId = useId();
    const panel = useRef<HTMLDialogElement>(null);
    const [footerHost, setFooterHost] = useState<HTMLElement | null>(null);
    const [headerHost, setHeaderHost] = useState<HTMLElement | null>(null);

    useEffect(() => {
        const dialog = panel.current;
        if (!dialog) return;
        const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const unlock = lockPage();
        // The native modal top layer makes the rest of the UI inert, including nested overlays.
        dialog.showModal();
        return () => {
            dialog.close();
            unlock();
            // Wait for the opening control to be enabled again after the state update.
            requestAnimationFrame(() => { if (previous?.isConnected) previous.focus(); });
        };
    }, []);

    // Keep studio tokens inherited without letting a disabled editor fieldset disable the close controls.
    const host = document.querySelector('.studio-root') ?? document.body;
    return createPortal(<dialog ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={describedBy}
        className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-3xl overflow-hidden rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-0 text-[var(--studio-text)] shadow-xl backdrop:bg-black/40"
        onCancel={(event) => { event.preventDefault(); event.stopPropagation(); if (!busy) onClose(); }}
        onClick={(event) => {
            if (busy || event.target !== event.currentTarget) return;
            const rect = event.currentTarget.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
        }}
        onKeyDown={(event) => {
            if (event.key === 'Escape') event.stopPropagation();
            if (event.key !== 'Tab') return;
            const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], [tabindex]')]
                .filter((element) => !element.matches(':disabled') && element.tabIndex >= 0 && element.getClientRects().length > 0);
            const first = controls[0];
            const last = controls.at(-1);
            if (!first || !last) { event.preventDefault(); event.currentTarget.focus(); return; }
            if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
                event.preventDefault(); last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault(); first.focus();
            }
        }}>
        <div className="flex max-h-[calc(100dvh-2rem)] flex-col">
            <header className="flex shrink-0 items-center justify-between gap-4 border-b border-[var(--studio-border)] px-5 py-4">
                <div className="flex min-w-0 items-center gap-2"><h2 id={titleId} className="text-base font-semibold">{title}</h2>{help && <Help label={title} text={help} below wide />}</div>
                <div className="flex items-center gap-3">{headerAction}<span ref={setHeaderHost} className="contents" /><button type="button" aria-label={`${title}を閉じる`} disabled={busy} onClick={() => { if (!busy) onClose(); }} className="rounded-md p-2 text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40"><X size={18} aria-hidden="true" /></button></div>
            </header>
            <OverlayHeaderContext.Provider value={headerHost}>
                <OverlayFooterContext.Provider value={footerHost}>
                    <div className="min-h-0 overflow-y-auto overscroll-contain p-5">{children}</div>
                </OverlayFooterContext.Provider>
            </OverlayHeaderContext.Provider>
            <footer ref={setFooterHost} className="flex shrink-0 flex-wrap items-center justify-end gap-3 border-t border-[var(--studio-border)] px-5 py-4 empty:hidden">
                {footer}
            </footer>
        </div>
    </dialog>, host);
}
