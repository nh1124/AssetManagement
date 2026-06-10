import { api } from "./api-client.js";
import { toStructured } from "./utils.js";

type McpWriteMode = "direct_write" | "change_request";

interface AiExecutionSettings {
  mcp_write_mode: McpWriteMode;
  supported_change_request_operations: string[];
}

interface ChangeRequestInput {
  resource: string;
  action: string;
  risk: "low" | "medium" | "high" | "critical";
  target_ref?: Record<string, unknown>;
  input_payload?: Record<string, unknown>;
}

const DIRECT_WRITE_SETTINGS: AiExecutionSettings = {
  mcp_write_mode: "direct_write",
  supported_change_request_operations: [],
};

export async function getAiExecutionSettings(): Promise<AiExecutionSettings> {
  try {
    return await api.get<AiExecutionSettings>("/ai/execution-settings");
  } catch {
    return DIRECT_WRITE_SETTINGS;
  }
}

export async function shouldCreateChangeRequest(): Promise<boolean> {
  const settings = await getAiExecutionSettings();
  return settings.mcp_write_mode === "change_request";
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
        `Change request mode is enabled in Settings. Created approval request${idText}; no direct write was applied.\n` +
        "Open Approval Inbox to review, approve, and apply it.\n\n" +
        JSON.stringify(data, null, 2),
    }],
    structuredContent: toStructured(data),
  };
}

export function changeRequestUnsupportedResult(operation: string) {
  const data = {
    blocked: true,
    operation,
    reason: "change_request_required",
    message:
      "Change request mode is enabled in Settings, but this MCP operation is not yet supported by the approval buffer. No direct write was applied.",
  };
  return {
    content: [{ type: "text" as const, text: data.message }],
    structuredContent: toStructured(data),
  };
}

export function directWriteMessage(label: string, data: unknown): string {
  return `Direct write mode is enabled in Settings. ${label}:\n${JSON.stringify(data, null, 2)}`;
}
