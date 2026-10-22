import { useConfirm } from '../../components/useConfirm';
import { useRef, useState } from 'react';
import { checkDataHealth, repairDataHealth } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { DataHealthIssue } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { labels, tr } from '../../i18n';

const buttonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';
const SEVERITY_LABELS = labels<DataHealthIssue['severity']>({ ok: ['正常', 'OK'], warning: ['警告', 'Warning'], error: ['エラー', 'Error'] });
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
        && Number.isFinite(Number(value))) return `${formatCurrency(Number(value), currency)}${tr(`（${currency}）`, ` (${currency})`)}`;
    if (typeof value === 'boolean') return value ? tr('はい', 'Yes') : tr('いいえ', 'No');
    return value === '' ? tr('（空欄）', '(empty)') : String(value);
}

function IssueCard({ issue, currency }: { issue: DataHealthIssue; currency: string }) {
    // Each check owns its item schema, so columns come from the first reported item.
    const columns = Object.keys(issue.items[0] ?? {});
    return (
        <article className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div><h3 className="text-sm font-semibold">{issue.title}</h3><p className="mt-1 break-all font-mono text-xs text-[var(--studio-text-muted)]">{issue.code}</p></div>
                <div className="flex flex-wrap gap-3 text-xs"><span className={SEVERITY_COLORS[issue.severity]}>{tr('重要度：', 'Severity: ')}{SEVERITY_LABELS[issue.severity]}</span><span>{tr(`件数：${issue.count}件`, `Count: ${issue.count}`)}</span><span>{issue.repairable ? tr('自動修復可能', 'Can be repaired automatically') : tr('確認・手動対応が必要', 'Needs checking by hand')}</span></div>
            </div>
            <p className="whitespace-pre-wrap text-sm text-[var(--studio-text-muted)]">{issue.detail}</p>
            {columns.length ? (
                <div className="overflow-x-auto rounded-md border border-[var(--studio-border)]">
                    <table className="w-full text-left text-xs">
                        <caption className="sr-only">{tr(`${issue.title}の対象データ`, `Data for ${issue.title}`)}</caption>
                        <thead className="border-b border-[var(--studio-border)] bg-[var(--studio-bg)] text-[var(--studio-text-muted)]"><tr>{columns.map((key) => <th scope="col" key={key} className="whitespace-nowrap px-3 py-2 font-medium">{key}</th>)}</tr></thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {issue.items.map((item, index) => {
                                const code = typeof item.currency === 'string' ? item.currency : currency;
                                return <tr key={index}>{columns.map((key) => <td key={key} className="max-w-sm whitespace-pre-wrap break-words px-3 py-2 align-top">{itemValue(item[key], key, code)}</td>)}</tr>;
                            })}
                        </tbody>
                    </table>
                </div>
            ) : <p className="text-xs text-[var(--studio-text-muted)]">{tr('対象データの明細はありません。', 'No details.')}</p>}
        </article>
    );
}

function HealthForClient({ clientId, clientName, currency }: { clientId: number; clientName?: string; currency: string }) {
    const confirm = useConfirm();
    const { data, setData, loading, error, reload } = useResource(checkDataHealth);
    const [repairing, setRepairing] = useState(false);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const repairable = data?.issues.some((issue) => issue.count > 0 && issue.repairable) ?? false;

    const repair = async () => {
        if (inFlight.current || loading || error || !data || !repairable || !clientName) return;
        if (!(await confirm(tr(`「${clientName}」（クライアント #${clientId}）の自動修復可能な問題をすべて修復しますか？\nこの操作は実データに書き込みます。修復後に再検査します。`, `Repair every automatically repairable issue of “${clientName}” (client #${clientId})?\nThis writes to real data. The check runs again afterwards.`), tr('修復する', 'Repair')))) return;
        inFlight.current = true;
        setRepairing(true);
        setOperationError('');
        setConfirmation('');
        try {
            const result = await repairDataHealth();
            // Preserve the server's repair result while a fresh check is requested.
            setData(result.health);
            setConfirmation(tr('修復処理が完了しました。', 'Repair finished.'));
            reload();
        } catch (failure: unknown) {
            setOperationError(tr(`修復できませんでした。${assetErrorMessage(failure)}`, `Could not repair. ${assetErrorMessage(failure)}`));
        } finally {
            inFlight.current = false;
            setRepairing(false);
        }
    };

    return (
        <section className="space-y-4">
            <div className="rounded-lg border border-[var(--studio-warning)] bg-[var(--studio-surface)] p-4 text-sm text-[var(--studio-warning)]">
                <p className="font-semibold">{tr('UI再構築のデバッグ用画面です。リリース前に削除してください。', 'A debug screen for the UI rebuild. Delete it before release.')}</p>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex gap-2"><button type="button" onClick={reload} disabled={loading || repairing} className={buttonClass}>{tr('再検査', 'Check again')}</button><button type="button" onClick={() => void repair()} disabled={loading || repairing || Boolean(error) || !repairable || !clientName} className={buttonClass}>{repairing ? tr('修復中…', 'Repairing…') : tr('修復する', 'Repair')}</button></div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('データ健全性を検査しています…', 'Checking data health…')}</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('検査結果を取得できませんでした。', 'Could not load the check results. ')}{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && <div className="space-y-4" aria-busy={loading || repairing}>
                <p className="rounded-md bg-[var(--studio-accent-soft)] px-4 py-3 text-sm">{tr('問題が見つからなかった検査：', 'Checks with no issues: ')}{data.issues.filter((issue) => issue.count === 0).length}</p>
                {data.issues.filter((issue) => issue.count > 0).map((issue) => <IssueCard key={issue.code} issue={issue} currency={currency} />)}
                {!repairable && data.issues.some((issue) => issue.count > 0) && <p className="text-xs text-[var(--studio-text-muted)]">{tr('自動修復できる問題はありません。各項目を確認してください。', 'Nothing can be repaired automatically. Check each item.')}</p>}
            </div>}
        </section>
    );
}

export default function DataHealth() {
    const { clientId, currentClient } = useClient();
    // Reusing results across clients would make a real-data repair target ambiguous.
    return <HealthForClient key={clientId} clientId={clientId} clientName={currentClient?.id === clientId ? currentClient.name : undefined} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
