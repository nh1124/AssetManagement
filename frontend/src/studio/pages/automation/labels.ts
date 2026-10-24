import type { AiAuthorization, AiChangeRequestStatus, AiOperationDecision, AiOperationMode, AiOperationRisk, AiOperationSource } from '../../../types';
import { labels, tr } from '../../i18n';

export const MODE_LABELS = labels<AiOperationMode>({
    allow: ['許可', 'Allow'], approval: ['承認が必要', 'Needs approval'], deny: ['禁止', 'Deny'],
});
export const RISK_LABELS = labels<AiOperationRisk>({
    low: ['低', 'Low'], medium: ['中', 'Medium'], high: ['高', 'High'], critical: ['重大', 'Critical'],
});
export const STATUS_LABELS = labels<AiChangeRequestStatus>({
    draft: ['下書き', 'Draft'], pending: ['承認待ち', 'Pending'], approved: ['承認済み', 'Approved'], applied: ['適用済み', 'Applied'],
    rejected: ['却下済み', 'Rejected'], expired: ['期限切れ', 'Expired'], failed: ['失敗', 'Failed'],
});
/** How 作り直す works, for the 「?」 beside it. */
export const rebuildHelp = () => tr('今のデータで変更内容を作り直し、承認待ちに戻します。もう一度承認してから適用します。', 'Rebuilds the change from the current data and returns it to pending. Approve it again before applying.');

/** Why a request failed, in the user's words; the backend's message for anything else. */
export function failureReason(result: Record<string, unknown>) {
    if (result.error === 'precondition_conflict') return tr('承認の後に対象のデータが変わりました。', 'The data changed after the approval.');
    const message = typeof result.message === 'string' ? result.message : '';
    return message ? tr(`適用できませんでした（${message}）。`, `Could not apply (${message}).`) : tr('適用できませんでした。', 'Could not apply.');
}

export const SOURCE_LABELS = labels<AiOperationSource>({
    frontend: ['画面', 'Screen'], mcp_http: ['MCP（HTTP）', 'MCP (HTTP)'], mcp_stdio: ['MCP（標準入出力）', 'MCP (stdio)'], backend: ['バックエンド', 'Backend'],
});
export const DECISION_LABELS = labels<AiOperationDecision>({
    allowed: ['許可', 'Allowed'], denied: ['拒否', 'Denied'], approval_required: ['承認が必要', 'Needs approval'], applied: ['適用済み', 'Applied'], failed: ['失敗', 'Failed'],
});
/** What let an AI operation through or stopped it (WP34). */
export const AUTHORIZATION_LABELS = labels<AiAuthorization>({
    read: ['読み取り', 'Read'],
    direct_policy: ['直接実行（操作の権限で許可）', 'Ran directly (allowed by the operation’s permission)'],
    // Only rows from before the operation list (WP36).
    direct_mode: ['直接書き込み（書き込み方式で許可）', 'Written directly (allowed by the write mode)'],
    change_request: ['承認リクエストを作成', 'Change request created'],
    human_approved: ['人の承認の後に適用', 'Applied after a person approved'],
    refused_scope: ['拒否（AI には許されない操作）', 'Refused (not allowed to the AI)'],
    refused_policy: ['拒否（操作の権限）', 'Refused (the operation’s permission)'],
    refused_mode: ['拒否（承認リクエスト方式）', 'Refused (change-request mode)'],
    failed: ['失敗', 'Failed'],
});
export const buttonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';
export const inputClass = 'rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] px-3 py-2 text-sm text-[var(--studio-text)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
