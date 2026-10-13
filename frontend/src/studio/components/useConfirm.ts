import { useCallback, useContext, useEffect, useId } from 'react';
import { ConfirmationContext } from './confirmationContext';

export function useConfirm() {
    const context = useContext(ConfirmationContext);
    if (!context) throw new Error('Confirmation requires ConfirmProvider');
    const owner = useId();
    const { request, cancel } = context;
    // Leaving a route or switching clients cancels its pending write decision.
    useEffect(() => () => cancel(owner), [cancel, owner]);
    return useCallback((body: string, label: string, title = '操作の確認') =>
        new Promise<boolean>((resolve) => request({ owner, body, label, title, resolve })), [owner, request]);
}
