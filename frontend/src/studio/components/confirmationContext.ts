import { createContext } from 'react';

export interface ConfirmationRequest {
    owner: string; body: string; label: string; title: string;
    resolve: (accepted: boolean) => void;
}

export const ConfirmationContext = createContext<{
    request: (request: ConfirmationRequest) => void;
    cancel: (owner: string) => void;
} | null>(null);
