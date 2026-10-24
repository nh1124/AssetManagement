import type { AiMcpWriteMode, AiOperationEntry, AiOperationMode } from '../../../types';

/** What the AI can do with an operation now (WP36 §3.3), from its permission and the MCP write mode. */
export type OperationEffect =
    | 'read' | 'no_read'
    | 'direct' | 'available' | 'through_approval'
    | 'not_in_mode' | 'no_requests' | 'denied';

type EffectFacts = Pick<AiOperationEntry, 'kind' | 'approval' | 'by_write_mode'>;

/** The backend's order (ai_policy_service.mcp_refusal): deny, then reads and the change-request
 * operations pass, then the write mode, then "approval". `requests` says whether the AI may create
 * a change request at all, since every way through approval starts with one. */
export function operationEffect(operation: EffectFacts, mode: AiOperationMode, writeMode: AiMcpWriteMode, requests: boolean): OperationEffect {
    if (operation.kind === 'read') return mode === 'deny' ? 'no_read' : 'read';
    if (mode === 'deny') return 'denied';
    if (!operation.by_write_mode) return 'available';
    if (mode === 'allow' && writeMode === 'direct_write') return 'direct';
    if (!operation.approval) return 'not_in_mode';
    return requests ? 'through_approval' : 'no_requests';
}

export type KindFilter = 'all' | 'read' | 'write';

/** A search matches the operation's name in either language, its key or one of its tools. */
export function operationMatches(operation: Pick<AiOperationEntry, 'kind' | 'key' | 'ja' | 'en' | 'tools'>, query: string, kind: KindFilter) {
    if (kind !== 'all' && operation.kind !== kind) return false;
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const text = [operation.ja, operation.en, operation.key, ...operation.tools].join('\n').toLowerCase();
    return words.every((word) => text.includes(word));
}
