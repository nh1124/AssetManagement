import { api, ApiError } from "./api-client.js";
import { toStructured } from "./utils.js";

interface ChangeRequestInput {
  resource: string;
  action: string;
  target_ref?: Record<string, unknown>;
  input_payload?: Record<string, unknown>;
}

// The backend's refusals a change request can take over (WP36): the change-request write
// mode, and an operation whose permission is "needs approval". The backend decides and
// records; the MCP server does not read the write mode before a write.
const CHANGE_REQUEST_REFUSALS = new Set(["change_request_mode", "operation_needs_approval"]);

export function needsChangeRequest(error: unknown): boolean {
  return error instanceof ApiError && error.refusal !== undefined && CHANGE_REQUEST_REFUSALS.has(error.refusal);
}

export async function createChangeRequestResult(input: ChangeRequestInput) {
  const data = await api.post<Record<string, unknown>>("/ai/change-requests", {
    ...input,
    status: "pending",
  });
  const idText = data.id ? ` #${data.id}` : "";
  return {
    content: [{
      type: "text" as const,
      text:
        `This write needs a person's approval (the write mode or the operation's permission in the app). Created approval request${idText}; no direct write was applied.\n` +
        "A person reviews, approves and applies it in the app's approval requests.\n\n" +
        JSON.stringify(data, null, 2),
    }],
    structuredContent: toStructured(data),
  };
}

/** The direct write; when the backend answers that it needs approval, a change request for it instead. */
export async function writeOrRequestChange(label: string, write: () => Promise<unknown>, request: ChangeRequestInput) {
  let data: unknown;
  try {
    data = await write();
  } catch (error) {
    if (needsChangeRequest(error)) return createChangeRequestResult(request);
    throw error;
  }
  return {
    content: [{ type: "text" as const, text: directWriteMessage(label, data) }],
    structuredContent: toStructured(data),
  };
}

export function directWriteMessage(label: string, data: unknown): string {
  return `Direct write (allowed without approval). ${label}:\n${JSON.stringify(data, null, 2)}`;
}
