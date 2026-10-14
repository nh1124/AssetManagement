import { createContext } from 'react';

// Undefined means a standalone editor; null means its overlay footer is mounting.
export const OverlayFooterContext = createContext<HTMLElement | null | undefined>(undefined);
