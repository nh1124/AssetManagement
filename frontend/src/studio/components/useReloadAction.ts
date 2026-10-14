import { useContext, useEffect, useId, useRef } from 'react';
import { ReloadContext } from './reloadContext';

export function useReloadAction(run: () => void, disabled = false, active = true) {
    const context = useContext(ReloadContext);
    const register = context?.register;
    const id = useId();
    const latest = useRef(run);
    useEffect(() => { latest.current = run; }, [run]);
    // Refresh mounted readers without remounting editors or opening any details.
    useEffect(() => {
        if (!register || !active) return;
        return register(id, { run: () => latest.current(), disabled });
    }, [register, id, disabled, active]);
}
