import type { AiChangeRequest } from '../../../types';
import { formatCurrency } from '../../../utils/currency';

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function valueText(value: unknown, field: string, currency: string): string {
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

export default function DiffRows({ change, currency }: {
    change: Pick<AiChangeRequest, 'diff' | 'before_snapshot' | 'after_snapshot'>;
    currency: string;
}) {
    const changes = change.diff.changes;
    const rows = Array.isArray(changes) ? changes.filter(isRecord).map((item) => ({
        field: String(item.field ?? ''), before: item.before, after: item.after,
    })).filter((item) => item.field) : Object.entries(change.diff).map(([field, after]) => ({ field, before: undefined, after }));
    const beforeCurrency = typeof change.before_snapshot.currency === 'string' ? change.before_snapshot.currency : currency;
    const afterCurrency = typeof change.after_snapshot.currency === 'string' ? change.after_snapshot.currency : currency;

    return rows.length ? (
        <div className="overflow-x-auto rounded-md border border-[var(--studio-border)]">
            <table className="w-full text-left text-xs">
                <caption className="sr-only">変更差分</caption>
                <thead className="border-b border-[var(--studio-border)] bg-[var(--studio-bg)] text-[var(--studio-text-muted)]">
                    <tr><th scope="col" className="px-3 py-2 font-medium">項目</th><th scope="col" className="px-3 py-2 font-medium">変更前</th><th scope="col" className="px-3 py-2 font-medium">変更後</th></tr>
                </thead>
                <tbody className="divide-y divide-[var(--studio-border)]">
                    {rows.map((row, index) => <tr key={`${row.field}:${index}`}>
                        <th scope="row" className="px-3 py-2 align-top font-medium">{row.field}</th>
                        <td className="min-w-36 whitespace-pre-wrap break-words px-3 py-2 align-top text-[var(--studio-text-muted)]">{valueText(row.before, row.field, beforeCurrency)}</td>
                        <td className="min-w-36 whitespace-pre-wrap break-words px-3 py-2 align-top">{valueText(row.after, row.field, afterCurrency)}</td>
                    </tr>)}
                </tbody>
            </table>
        </div>
    ) : <p className="text-xs text-[var(--studio-text-muted)]">項目の変更はありません。</p>;
}
