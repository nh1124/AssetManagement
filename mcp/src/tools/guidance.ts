// ============================================================
// Agent guidance and validation tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  fetchAccounts,
  previewTransactionPayload,
  transactionPayloadSchema,
} from "../domain-guidance.js";
import { toStructured } from "../utils.js";

export function registerGuidanceTools(server: McpServer): void {
  server.registerTool(
    "validate_transaction_payload",
    {
      title: "Validate transaction payload",
      description:
        "Validates a transaction payload against AssetManagement accounting rules without saving it. Use before transactions_create or transaction_batches_create.",
      inputSchema: transactionPayloadSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const accounts = await fetchAccounts();
        const result = previewTransactionPayload(input, accounts);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          structuredContent: toStructured(result),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
