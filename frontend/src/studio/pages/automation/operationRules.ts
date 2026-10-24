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

/** A row shows a tag only where the chosen permission is not what happens (WP37):
 * "allow" that goes through approval, or a permission the write mode makes unusable. */
export function effectTag(operation: EffectFacts, mode: AiOperationMode, writeMode: AiMcpWriteMode, requests: boolean): 'via_approval' | 'unavailable' | null {
    const effect = operationEffect(operation, mode, writeMode, requests);
    if (effect === 'not_in_mode' || effect === 'no_requests') return 'unavailable';
    return effect === 'through_approval' && mode === 'allow' ? 'via_approval' : null;
}
