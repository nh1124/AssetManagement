import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { ReloadContext, type ReloadAction } from './reloadContext';
import { useReloadAction } from './useReloadAction';

export function ReloadRegistration({ run, disabled = false, active = true }: {
    run: () => void; disabled?: boolean; active?: boolean;
}) {
    useReloadAction(run, disabled, active);
    return null;
}

export default function ReloadScope({ children }: { children: ReactNode }) {
    const [actions, setActions] = useState<Map<string, ReloadAction>>(() => new Map());
    const register = useCallback((id: string, action: ReloadAction) => {
        setActions((previous) => new Map(previous).set(id, action));
        return () => setActions((previous) => { const next = new Map(previous); next.delete(id); return next; });
    }, []);
    const context = useMemo(() => ({ actions, register }), [actions, register]);
    return <ReloadContext.Provider value={context}>
        {actions.size > 0 && <div className="mb-4 flex justify-end">
            <button type="button" disabled={[...actions.values()].some((action) => action.disabled)} onClick={() => {
                for (const action of actions.values()) action.run();
            }} className="rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40">再読み込み</button>
        </div>}
        {children}
    </ReloadContext.Provider>;
}
