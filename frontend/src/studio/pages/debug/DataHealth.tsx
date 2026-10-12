import { useRef, useState } from 'react';
import { checkDataHealth, repairDataHealth } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { DataHealthIssue } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';

const buttonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';
const SEVERITY_LABELS: Record<DataHealthIssue['severity'], string> = { ok: '正常', warning: '警告', error: 'エラー' };
const SEVERITY_COLORS: Record<DataHealthIssue['severity'], string> = {
    ok: 'text-[var(--studio-positive)]', warning: 'text-[var(--studio-warning)]', error: 'text-[var(--studio-danger)]',
};

function itemValue(value: unknown, key: string, currency: string): string {
    if (value == null) return '—';
    if (Array.isArray(value)) return value.length ? value.map((entry) => itemValue(entry, key, currency)).join('\n') : '[]';
    if (typeof value === 'object') {
        const record = value as Record<string, unknown>;
        const code = typeof record.currency === 'string' ? record.currency : currency;
        return Object.entries(record).map(([field, entry]) => `${field}: ${itemValue(entry, field, code)}`).join('\n') || '{}';
    }
    // Issue items vary; format named monetary values without mistaking IDs or counts for money.
    if (/(?:^|_)(amount|balance|debit|credit|cost|price|total|difference|claim|planned)$/.test(key)
        && (typeof value === 'number' || (typeof value === 'string' && value.trim() !== ''))
        && Number.isFinite(Number(value))) return `${formatCurrency(Number(value), currency)}（${currency}）`;
    if (typeof value === 'boolean') return value ? 'はい' : 'いいえ';
    return value === '' ? '（空欄）' : String(value);
}

function IssueCard({ issue, currency }: { issue: DataHealthIssue; currency: string }) {
    // Each check owns its item schema, so columns come from the first reported item.
    const columns = Object.keys(issue.items[0] ?? {});
    return (
        <article className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div><h3 className="text-sm font-semibold">{issue.title}</h3><p className="mt-1 break-all font-mono text-xs text-[var(--studio-text-muted)]">{issue.code}</p></div>
                <div className="flex flex-wrap gap-3 text-xs"><span className={SEVERITY_COLORS[issue.severity]}>重要度：{SEVERITY_LABELS[issue.severity]}</span><span>件数：{issue.count}件</span><span>{issue.repairable ? '自動修復可能' : '確認・手動対応が必要'}</span></div>
            </div>
            <p className="whitespace-pre-wrap text-sm text-[var(--studio-text-muted)]">{issue.detail}</p>
            {columns.length ? (
                <div className="overflow-x-auto rounded-md border border-[var(--studio-border)]">
                    <table className="w-full text-left text-xs">
                        <caption className="sr-only">{issue.title}の対象データ</caption>
                        <thead className="border-b border-[var(--studio-border)] bg-[var(--studio-bg)] text-[var(--studio-text-muted)]"><tr>{columns.map((key) => <th scope="col" key={key} className="whitespace-nowrap px-3 py-2 font-medium">{key}</th>)}</tr></thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {issue.items.map((item, index) => {
                                const code = typeof item.currency === 'string' ? item.currency : currency;
                                return <tr key={index}>{columns.map((key) => <td key={key} className="max-w-sm whitespace-pre-wrap break-words px-3 py-2 align-top">{itemValue(item[key], key, code)}</td>)}</tr>;
                            })}
                        </tbody>
                    </table>
                </div>
            ) : <p className="text-xs text-[var(--studio-text-muted)]">対象データの明細はありません。</p>}
        </article>
    );
}

function HealthForClient({ clientId, clientName, currency }: { clientId: number; clientName?: string; currency: string }) {
    const { data, setData, loading, error, reload } = useResource(checkDataHealth);
    const [repairing, setRepairing] = useState(false);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const repairable = data?.issues.some((issue) => issue.count > 0 && issue.repairable) ?? false;

    const repair = async () => {
        if (inFlight.current || loading || error || !data || !repairable || !clientName) return;
        if (!window.confirm(`「${clientName}」（クライアント #${clientId}）の自動修復可能な問題をすべて修復しますか？\nこの操作は実データに書き込みます。修復後に再検査します。`)) return;
        inFlight.current = true;
        setRepairing(true);
        setOperationError('');
        setConfirmation('');
        try {
            const result = await repairDataHealth();
            // Preserve the server's repair result while a fresh check is requested.
            setData(result.health);
            setConfirmation('修復処理が完了しました。');
            reload();
        } catch (failure: unknown) {
            setOperationError(`修復できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            inFlight.current = false;
            setRepairing(false);
        }
    };

    return (
        <section className="space-y-4">
            <div className="rounded-lg border border-[var(--studio-warning)] bg-[var(--studio-surface)] p-4 text-sm text-[var(--studio-warning)]">
                <p className="font-semibold">UI再構築のデバッグ用画面です。リリース前に削除してください。</p>
                <p className="mt-1">データ健全性は通知と、問題のある入力箇所での修復案内に統合します。</p>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div><h2 className="text-lg font-semibold">データ健全性</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">対象：{clientName ?? 'クライアントを確認中…'}（#{clientId}）</p></div>
                <div className="flex gap-2"><button type="button" onClick={reload} disabled={loading || repairing} className={buttonClass}>再検査</button><button type="button" onClick={() => void repair()} disabled={loading || repairing || Boolean(error) || !repairable || !clientName} className={buttonClass}>{repairing ? '修復中…' : '修復する'}</button></div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">データ健全性を検査しています…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">検査結果を取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && <div className="space-y-4" aria-busy={loading || repairing}>
                <p className="rounded-md bg-[var(--studio-accent-soft)] px-4 py-3 text-sm">問題が見つからなかった検査：{data.issues.filter((issue) => issue.count === 0).length}件</p>
                {data.issues.filter((issue) => issue.count > 0).map((issue) => <IssueCard key={issue.code} issue={issue} currency={currency} />)}
                {!repairable && data.issues.some((issue) => issue.count > 0) && <p className="text-xs text-[var(--studio-text-muted)]">自動修復できる問題はありません。各項目を確認してください。</p>}
            </div>}
        </section>
    );
}

export default function DataHealth() {
    const { clientId, currentClient } = useClient();
    // Reusing results across clients would make a real-data repair target ambiguous.
    return <HealthForClient key={clientId} clientId={clientId} clientName={currentClient?.id === clientId ? currentClient.name : undefined} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
