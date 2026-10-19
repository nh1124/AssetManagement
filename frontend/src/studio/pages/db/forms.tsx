import { useEffect, useRef, useState } from 'react';
import { getAccounts, getCapsules } from '../../../api';
import type { Account } from '../../../types';
import { assetErrorMessage } from '../../useResource';

export type DatabaseAccount = Omit<Account, 'account_type'> & { account_type: Account['account_type'] };
export const ACCOUNT_TYPES: Record<DatabaseAccount['account_type'], string> = {
    asset: '資産', liability: '負債', income: '収入', expense: '費用',
};

export const buttonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';
export const inputClass = 'w-full rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] px-3 py-2 text-sm text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
export const primaryClass = 'rounded-md bg-[var(--studio-accent)] px-4 py-2 text-xs font-medium text-[var(--studio-accent-text)] hover:opacity-90 disabled:opacity-40';

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
