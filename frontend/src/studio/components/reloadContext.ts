import { createContext } from 'react';

export interface ReloadAction { run: () => void; disabled: boolean }
export const ReloadContext = createContext<{
    actions: Map<string, ReloadAction>;
    register: (id: string, action: ReloadAction) => () => void;
} | null>(null);
