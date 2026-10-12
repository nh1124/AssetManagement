import { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';

export function assetErrorMessage(error: unknown): string {
    if (isAxiosError<{ detail?: unknown; message?: string }>(error)) {
        const data = error.response?.data;
        if (typeof data?.detail === 'string') return data.detail;
        if (Array.isArray(data?.detail)) {
            const messages = data.detail.flatMap((entry: unknown) =>
                typeof entry === 'object' && entry !== null && 'msg' in entry && typeof entry.msg === 'string'
                    ? [entry.msg] : []);
            if (messages.length) return messages.join('、');
        }
        if (typeof data?.message === 'string') return data.message;
    }
    return error instanceof Error ? error.message : '通信に失敗しました。もう一度お試しください。';
}

export function useAssetData<T>(load: () => Promise<T>) {
    const [data, setData] = useState<T | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        let stale = false;
        void load().then((result) => {
            if (!stale) setData(result);
        }).catch((failure: unknown) => {
            if (!stale) setError(assetErrorMessage(failure));
        }).finally(() => {
            if (!stale) setLoading(false);
        });
        // A response from a previous tab visit must not update the current view.
        return () => { stale = true; };
    }, [load, revision]);

    const reload = () => {
        setLoading(true);
        setError('');
        setRevision((value) => value + 1);
    };

    return { data, setData, loading, error, reload };
}
