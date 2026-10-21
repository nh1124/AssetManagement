import type { AiChangeRequestStatus, AiOperationDecision, AiOperationMode, AiOperationRisk, AiOperationSource } from '../../../types';

export const MODE_LABELS: Record<AiOperationMode, string> = {
    deny: '拒否', allow_read: '読み取りのみ許可', require_approval: '承認が必要', allow_execute: '実行を許可',
};
export const RISK_LABELS: Record<AiOperationRisk, string> = {
    low: '低', medium: '中', high: '高', critical: '重大',
};
export const STATUS_LABELS: Record<AiChangeRequestStatus, string> = {
    draft: '下書き', pending: '承認待ち', approved: '承認済み', applied: '適用済み', rejected: '却下済み', expired: '期限切れ', failed: '失敗',
};
/** How 作り直す works, for the 「?」 beside it. */
export const REBUILD_HELP = '今のデータで変更内容を作り直し、承認待ちに戻します。もう一度承認してから適用します。';

/** Why a request failed, in the user's words; the backend's message for anything else. */
export function failureReason(result: Record<string, unknown>) {
    if (result.error === 'precondition_conflict') return '承認の後に対象のデータが変わりました。';
    const message = typeof result.message === 'string' ? result.message : '';
    return message ? `適用できませんでした（${message}）。` : '適用できませんでした。';
}

export const SOURCE_LABELS: Record<AiOperationSource, string> = {
    frontend: '画面', mcp_http: 'MCP（HTTP）', mcp_stdio: 'MCP（標準入出力）', backend: 'バックエンド',
};
export const DECISION_LABELS: Record<AiOperationDecision, string> = {
    allowed: '許可', denied: '拒否', approval_required: '承認が必要', applied: '適用済み', failed: '失敗',
};
export const buttonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';
export const inputClass = 'rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] px-3 py-2 text-sm text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
