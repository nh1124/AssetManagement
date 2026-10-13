import { useLocation } from 'react-router-dom';

export function useReturnTo(fallback: string): string {
    const { state } = useLocation();
    const routeState: unknown = state;
    // Only internal studio destinations can be restored from history state.
    if (typeof routeState === 'object' && routeState !== null && 'returnTo' in routeState
        && typeof routeState.returnTo === 'string' && routeState.returnTo.startsWith('/') && !routeState.returnTo.startsWith('//')) {
        return routeState.returnTo;
    }
    return fallback;
}
