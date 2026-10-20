import type { AiChangeRequest } from '../../../types';
import { diffRows } from './diffValues';

export default function DiffRows({ change, currency }: {
    change: Pick<AiChangeRequest, 'diff' | 'before_snapshot' | 'after_snapshot'>;
    currency: string;
}) {
    const rows = diffRows(change, currency);
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
                        <td className="min-w-36 whitespace-pre-wrap break-words px-3 py-2 align-top text-[var(--studio-text-muted)]">{row.before}</td>
                        <td className="min-w-36 whitespace-pre-wrap break-words px-3 py-2 align-top">{row.after}</td>
                    </tr>)}
                </tbody>
            </table>
        </div>
    ) : <p className="text-xs text-[var(--studio-text-muted)]">項目の変更はありません。</p>;
}
