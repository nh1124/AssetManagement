import { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { tr } from './i18n';

export function assetErrorMessage(error: unknown): string {
    if (isAxiosError<{ detail?: unknown; message?: string }>(error)) {
        const data = error.response?.data;
        if (typeof data?.detail === 'string') return data.detail;
        if (Array.isArray(data?.detail)) {
            const messages = data.detail.flatMap((entry: unknown) =>
                typeof entry === 'object' && entry !== null && 'msg' in entry && typeof entry.msg === 'string'
                    ? [entry.msg] : []);
            if (messages.length) return messages.join(tr('、', '; '));
        }
        if (typeof data?.message === 'string') return data.message;
    }
    return error instanceof Error ? error.message : tr('通信に失敗しました。もう一度お試しください。', 'The request failed. Try again.');
}

export function useResource<T>(load: () => Promise<T>) {
    const [data, setData] = useState<T | null>(null);
    const [loading, setLoading] = useState(true);
    const [failure, setFailure] = useState<{ load: () => Promise<T>; message: string } | null>(null);
    const [revision, setRevision] = useState(0);
    // An error belongs to the load that failed: a new month or filter starts without it.
    const error = failure && failure.load === load ? failure.message : '';

    useEffect(() => {
        let stale = false;
        void load().then((result) => {
            if (!stale) setData(result);
        }).catch((reason: unknown) => {
            if (!stale) setFailure({ load, message: assetErrorMessage(reason) });
        }).finally(() => {
            if (!stale) setLoading(false);
        });
        // A response from a previous tab visit must not update the current view.
        return () => { stale = true; };
    }, [load, revision]);

    const reload = () => {
        setLoading(true);
        setFailure(null);
        setRevision((value) => value + 1);
    };

    return { data, setData, loading, error, reload };
}
