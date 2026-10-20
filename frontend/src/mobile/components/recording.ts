import { createContext, useContext } from 'react';
import type { Transaction } from '../../types';

export interface Recording {
    /** Open the record sheet: empty, or on a transaction to change it. */
    open: (transaction?: Transaction) => void;
    /** Grows whenever a record is saved or deleted, so screens can load again. */
    revision: number;
    /** Something on a screen changed the ledger (a deletion, an approval). */
    changed: () => void;
}

export const RecordingContext = createContext<Recording>({ open: () => undefined, revision: 0, changed: () => undefined });

export function useRecording(): Recording {
    return useContext(RecordingContext);
}
