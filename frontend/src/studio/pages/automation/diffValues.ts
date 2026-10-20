import type { AiChangeRequest } from '../../../types';
import { formatCurrency } from '../../../utils/currency';

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function valueText(value: unknown, field: string, currency: string): string {
    if (value == null) return '—';
    if (Array.isArray(value)) return value.length ? value.map((item, index) => `${index + 1}. ${valueText(item, field, currency)}`).join('\n') : '[]';
    if (isRecord(value)) {
        const code = typeof value.currency === 'string' ? value.currency : currency;
        return Object.entries(value).map(([key, item]) => `${key}: ${valueText(item, key, code)}`).join('\n') || '{}';
    }
    // Match monetary field names, not arbitrary numbers such as account IDs or counts.
    if (/(?:^|[._])(amount|balance|debit|credit|cost|price|total|difference)$/.test(field)
        && (typeof value === 'number' || (typeof value === 'string' && value.trim() !== ''))
        && Number.isFinite(Number(value))) return `${formatCurrency(Number(value), currency)}（${currency}）`;
    if (typeof value === 'boolean') return value ? 'はい' : 'いいえ';
    return value === '' ? '（空欄）' : String(value);
}

/** A change request's fields, each with its value before and after, as text. */
export function diffRows(change: Pick<AiChangeRequest, 'diff' | 'before_snapshot' | 'after_snapshot'>, currency: string): Array<{ field: string; before: string; after: string }> {
    const changes = change.diff.changes;
    const rows = Array.isArray(changes) ? changes.filter(isRecord).map((item) => ({
        field: String(item.field ?? ''), before: item.before, after: item.after,
    })).filter((item) => item.field) : Object.entries(change.diff).map(([field, after]) => ({ field, before: undefined as unknown, after }));
    const beforeCurrency = typeof change.before_snapshot.currency === 'string' ? change.before_snapshot.currency : currency;
    const afterCurrency = typeof change.after_snapshot.currency === 'string' ? change.after_snapshot.currency : currency;
    return rows.map((row) => ({ field: row.field, before: valueText(row.before, row.field, beforeCurrency), after: valueText(row.after, row.field, afterCurrency) }));
}
