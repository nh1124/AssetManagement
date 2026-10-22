import { activeLocale, tr } from '../studio/i18n';
import type { Client } from './types';
export function date(value: string | null, dateOnly = false) {
    if (!value) return tr('—', '—');
    if (dateOnly && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    // API timestamps are naive UTC; display in the browser's timezone.
    const parsed = new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(activeLocale());
}
export function onOff(value: boolean) { return value ? tr('有効', 'Enabled') : tr('未設定', 'Not set'); }
export function clientStatuses(client: Client) {
    return [!client.is_active && tr('停止中', 'Suspended'), client.approval_pending && tr('承認待ち', 'Pending approval'),
        client.locked_until && new Date(`${client.locked_until.replace(/Z$/, '')}Z`).getTime() > Date.now() && tr('ロック中', 'Locked')]
        .filter(Boolean).join(tr('・', ' · ')) || tr('有効', 'Active');
}
