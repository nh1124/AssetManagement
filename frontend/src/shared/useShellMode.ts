import { useEffect, useState } from 'react';

export type ShellMode = 'desktop' | 'mobile';

const MOBILE_QUERY = '(max-width: 767px)';

export function useShellMode(): ShellMode {
    const [mode, setMode] = useState<ShellMode>(() => {
        if (typeof window === 'undefined') return 'desktop';
        return window.matchMedia(MOBILE_QUERY).matches ? 'mobile' : 'desktop';
    });

    useEffect(() => {
        const media = window.matchMedia(MOBILE_QUERY);
        const update = () => setMode(media.matches ? 'mobile' : 'desktop');

        update();
        media.addEventListener('change', update);
        return () => media.removeEventListener('change', update);
    }, []);

    return mode;
}
