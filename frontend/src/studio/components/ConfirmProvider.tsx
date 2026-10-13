import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import Confirm from './Confirm';
import { ConfirmationContext, type ConfirmationRequest } from './confirmationContext';

export default function ConfirmProvider({ children }: { children: ReactNode }) {
    const [pending, setPending] = useState<ConfirmationRequest | null>(null);
    const active = useRef<ConfirmationRequest | null>(null);
    const finish = useCallback((accepted: boolean) => {
        const current = active.current;
        active.current = null;
        setPending(null);
        current?.resolve(accepted);
    }, []);
    const request = useCallback((next: ConfirmationRequest) => {
        // A second click cannot replace a confirmation the user is already reading.
        if (active.current) { next.resolve(false); return; }
        active.current = next;
        setPending(next);
    }, []);
    const cancel = useCallback((owner: string) => {
        if (active.current?.owner === owner) finish(false);
    }, [finish]);
    const context = useMemo(() => ({ request, cancel }), [request, cancel]);
    return <ConfirmationContext.Provider value={context}>
        {children}
        {pending && <Confirm title={pending.title} confirmLabel={pending.label} onCancel={() => finish(false)} onConfirm={() => finish(true)}>{pending.body}</Confirm>}
    </ConfirmationContext.Provider>;
}
