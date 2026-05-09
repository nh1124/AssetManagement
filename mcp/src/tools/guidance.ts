// ============================================================
// Agent guidance and validation tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  chooseTransactionType,
  fetchAccounts,
  previewTransactionPayload,
  transactionPayloadSchema,
} from "../domain-guidance.js";
import { toStructured } from "../utils.js";

export function registerGuidanceTools(server: McpServer): void {
  server.registerTool(
    "help_choose_transaction_type",
    {
      title: "Choose transaction type",
      description:
        "Explains which transaction type to use from the user's intent and payment method. Use this before creating unfamiliar transactions.",
      inputSchema: z
        .object({
          intent: z.string().optional().describe("Natural language description of the intended entry"),
          payment_method: z.string().optional().describe("Payment method, e.g. cash, bank, credit card"),
          acquired_asset: z.boolean().optional().describe("True if the purchase should be capitalized as an asset"),
          affects_liability: z.boolean().optional().describe("True if the entry creates or pays down a liability"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      const result = chooseTransactionType(input);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        structuredContent: toStructured(result),
      };
    },
  );

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
