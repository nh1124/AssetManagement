import { activeLanguage, tr } from '../studio/i18n';

export class ApiError extends Error {
    readonly status: number;
    readonly code?: string;
    constructor(message: string, status: number, code?: string) {
        super(message);
        this.status = status;
        this.code = code;
    }
}
export class Cancelled extends Error {
    constructor() { super(tr('操作を取り消しました。', 'Operation cancelled.')); }
}
interface Hooks { unauthorized: (detail: string) => void; stepUp: () => Promise<void> }
interface Options { method?: string; body?: unknown; authenticate?: boolean; retry?: boolean }
function detailText(detail: unknown): string {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map(item => typeof item?.msg === 'string' ? item.msg : JSON.stringify(item)).join(tr('、', '; '));
    return detail ? JSON.stringify(detail) : tr('通信に失敗しました。', 'The request failed.');
}

/** Cookie-only client; retries exclusively after an explicit step-up refusal, once. */
export function createAdminApi(hooks: Hooks) {
    let stepUpFlight: Promise<void> | null = null;
    async function request<T>(path: string, options: Options = {}): Promise<T> {
        const response = await fetch(`/admin/api${path}`, {
            method: options.method ?? 'GET',
            credentials: 'same-origin',
            headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Accept-Language': activeLanguage() },
            ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
        });
        const data = await response.json().catch(() => ({}));
        if (response.status === 401 && options.authenticate !== false) hooks.unauthorized(detailText(data.detail));
        if (response.status === 403 && data.code === 'step_up_required' && options.retry !== false) {
            if (!stepUpFlight) {
                stepUpFlight = hooks.stepUp().finally(() => { stepUpFlight = null; });
            }
            await stepUpFlight;
            return request<T>(path, { ...options, retry: false });
        }
        if (!response.ok) throw new ApiError(detailText(data.detail), response.status, data.code);
        return data as T;
    }
    return {
        request,
        get: <T,>(path: string) => request<T>(path),
        post: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
        patch: <T,>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body }),
        put: <T,>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body }),
        delete: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
    };
}
export type AdminApi = ReturnType<typeof createAdminApi>;
export function queryString(values: Record<string, string | number | undefined>): string {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value));
    return `?${params}`;
}

/** UI-independent coordinator: concurrent refusals share one dialog and settle on dismissal. */
export function createAdminConnection(hooks: { unauthorized: (detail: string) => void; showStepUp: (open: boolean) => void }) {
    let pending: { resolve: () => void; reject: (error: Error) => void } | null = null;
    function finishStepUp(cancel = false) {
        const operation = pending; pending = null; hooks.showStepUp(false);
        if (cancel) operation?.reject(new Cancelled()); else operation?.resolve();
    }
    const api = createAdminApi({
        unauthorized: detail => { finishStepUp(true); hooks.unauthorized(detail); },
        stepUp: () => new Promise<void>((resolve, reject) => { pending = { resolve, reject }; hooks.showStepUp(true); }),
    });
    return { api, finishStepUp };
}
