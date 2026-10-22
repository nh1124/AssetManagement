import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { ConfirmationContext, type ConfirmationRequest } from '../../studio/components/confirmationContext';
import Sheet from './Sheet';
import { dangerButton, primaryButton, secondaryButton } from './ui';
import { tr } from '../../studio/i18n';

/** The studio's confirmation contract (useConfirm) answered by a bottom sheet. */
export default function MobileConfirm({ children }: { children: ReactNode }) {
    const [pending, setPending] = useState<ConfirmationRequest | null>(null);
    const active = useRef<ConfirmationRequest | null>(null);
    const finish = useCallback((accepted: boolean) => {
        const current = active.current;
        active.current = null;
        setPending(null);
        current?.resolve(accepted);
    }, []);
    const request = useCallback((next: ConfirmationRequest) => {
        // A second tap cannot replace a confirmation the user is already reading.
        if (active.current) { next.resolve(false); return; }
        active.current = next;
        setPending(next);
    }, []);
    const cancel = useCallback((owner: string) => {
        if (active.current?.owner === owner) finish(false);
    }, [finish]);
    const context = useMemo(() => ({ request, cancel }), [request, cancel]);
    const destructive = pending ? /削除|却下|取り消|Delete|Reject|Cancel|Discard|Remove/.test(pending.label) : false;
    return <ConfirmationContext.Provider value={context}>
        {children}
        {pending && <Sheet title={pending.title} onClose={() => finish(false)} footer={<div className="grid grid-cols-2 gap-3">
            <button type="button" onClick={() => finish(false)} className={secondaryButton}>{tr('やめる', 'Cancel')}</button>
            <button type="button" onClick={() => finish(true)} className={destructive ? dangerButton : primaryButton}>{pending.label}</button>
        </div>}>
            <p className="whitespace-pre-line text-sm leading-relaxed">{pending.body}</p>
        </Sheet>}
    </ConfirmationContext.Provider>;
}
