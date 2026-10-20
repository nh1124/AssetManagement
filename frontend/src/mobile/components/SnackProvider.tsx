import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { SnackContext, type SnackTone } from './snack';

interface Snack { id: number; message: string; tone: SnackTone }

export default function SnackProvider({ children }: { children: ReactNode }) {
    const [snack, setSnack] = useState<Snack | null>(null);
    const show = useCallback((message: string, tone: SnackTone = 'success') => setSnack({ id: Date.now(), message, tone }), []);
    useEffect(() => {
        if (!snack) return;
        const timer = window.setTimeout(() => setSnack(null), snack.tone === 'error' ? 6000 : 3200);
        return () => window.clearTimeout(timer);
    }, [snack]);
    const value = useMemo(() => show, [show]);
    return <SnackContext.Provider value={value}>
        {children}
        <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-[calc(5.5rem+env(safe-area-inset-bottom))] z-[60] flex justify-center px-4">
            {snack && <div key={snack.id} role={snack.tone === 'error' ? 'alert' : 'status'}
                className={`mobile-snack pointer-events-auto max-w-md rounded-2xl px-4 py-3 text-sm font-medium text-white shadow-[var(--mobile-shadow-raised)] ${snack.tone === 'error' ? 'bg-[var(--studio-danger)]' : 'bg-[var(--studio-rail)]'}`}>
                {snack.message}
            </div>}
        </div>
    </SnackContext.Provider>;
}
