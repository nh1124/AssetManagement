import { createContext } from 'react';

// Undefined means a standalone editor; null means its overlay footer is mounting.
export const OverlayFooterContext = createContext<HTMLElement | null | undefined>(undefined);
// The same for the slot beside the × button.
export const OverlayHeaderContext = createContext<HTMLElement | null | undefined>(undefined);
