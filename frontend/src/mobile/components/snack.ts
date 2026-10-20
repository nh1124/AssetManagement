import { createContext, useContext } from 'react';

export type SnackTone = 'success' | 'error' | 'info';

export const SnackContext = createContext<(message: string, tone?: SnackTone) => void>(() => undefined);

/** Say what just happened, briefly, above the tab bar. */
export function useSnack() {
    return useContext(SnackContext);
}
