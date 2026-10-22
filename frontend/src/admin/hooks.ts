import { useEffect, useRef, useState } from 'react';
import { tr } from '../studio/i18n';
import { Cancelled } from './api';
import { useAdmin } from './context';
export function useAction() {
    const lock = useRef(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    async function run(action: () => Promise<unknown>, success = tr('変更しました。', 'Updated.')) {
        if (lock.current) return;
        lock.current = true;
        setBusy(true); setError(''); setMessage('');
        try { await action(); setMessage(success); }
        catch (e) { if (!(e instanceof Cancelled)) setError(e instanceof Error ? e.message : tr('操作に失敗しました。', 'The operation failed.')); }
        finally { lock.current = false; setBusy(false); }
    }
    return { busy, error, message, run };
}

/** A response belongs to its exact query; old pages never flash under new filters. */
export function useQuery<T>(path: string | null) {
    const { api } = useAdmin();
    const [revision, setRevision] = useState(0);
    const [result, setResult] = useState<{ path: string; revision: number; data?: T; error?: string } | null>(null);
    useEffect(() => {
        if (path === null) return;
        let stale = false;
        void api.get<T>(path).then(data => {
            if (!stale) setResult({ path, revision, data });
        }).catch((error: unknown) => {
            if (!stale) setResult({ path, revision, error: error instanceof Error ? error.message : tr('読み込めませんでした。', 'Could not load.') });
        });
        return () => { stale = true; };
    }, [api, path, revision]);
    const current = result?.path === path && result.revision === revision ? result : null;
    return { data: current?.data ?? null, error: current?.error, loading: path !== null && current === null, reload: () => setRevision(value => value + 1) };
}
