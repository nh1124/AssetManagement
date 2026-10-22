import { useEffect, useRef, useState } from 'react';
import { getAccounts, getCapsules } from '../../../api';
import type { Account } from '../../../types';
import { assetErrorMessage } from '../../useResource';
import { tr } from '../../i18n';

export type DatabaseAccount = Omit<Account, 'account_type'> & { account_type: Account['account_type'] };
// Getters, so each read is in the active language.
export const ACCOUNT_TYPES: Record<DatabaseAccount['account_type'], string> = {
    get asset() { return tr('資産', 'Asset'); },
    get liability() { return tr('負債', 'Liability'); },
    get income() { return tr('収入', 'Income'); },
    get expense() { return tr('費用', 'Expense'); },
};

export { buttonClass, inputClass, primaryClass } from '../../components/controlStyles';

export async function loadAccounts(): Promise<DatabaseAccount[]> {
    // Inactive accounts remain editable and may still be referenced by definitions.
    const [active, inactive] = await Promise.all([getAccounts(undefined, true), getAccounts(undefined, false)]);
    const rows = new Map<number, DatabaseAccount>();
    for (const row of [...inactive, ...active]) rows.set(row.id, row);
    return [...rows.values()].sort((a, b) => a.name.localeCompare(b.name, 'ja'));
}

export async function loadLookups() {
    // Only identity and name are needed; capsule funding sources are outside this wave.
    const [accounts, capsules] = await Promise.all([loadAccounts(), getCapsules() as Promise<Array<{ id: number; name: string }>>]);
    return { accounts, capsules };
}

export function today() {
    // Use the user's calendar date rather than the UTC date around midnight.
    return new Date().toLocaleDateString('sv-SE');
}

// An action resolves to this when the user backed out midway: no message, no follow-up.
export const userCancelled = Symbol('cancelled');

export function useMutation() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const inFlight = useRef(false);
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const run = async (action: () => Promise<unknown>, confirmation: string, onSuccess?: () => void) => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        setError('');
        setMessage('');
        try {
            const result = await action();
            // Navigation or a client switch must not refresh the previous screen.
            if (mounted.current && result !== userCancelled) {
                setMessage(confirmation);
                onSuccess?.();
            }
        } catch (failure: unknown) {
            if (mounted.current) setError(assetErrorMessage(failure));
        } finally {
            inFlight.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    return { busy, error, message, run };
}
