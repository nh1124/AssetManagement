// ============================================================
// Budget month copy
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

type JsonObject = Record<string, unknown>;

const periodSchema = z.string().regex(/^\d{4}-\d{2}$/);

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function withoutUndefined(input: JsonObject): JsonObject {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

export function registerStrategyTools(server: McpServer): void {
  server.registerTool(
    "budget_plans_copy_period",
    {
      title: "Copy budget period",
      description: "Copies all active monthly plan lines from one period to another, replacing the target period.",
      inputSchema: z
        .object({
          source_period: periodSchema,
          target_period: periodSchema,
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/budget-plans/copy-period", withoutUndefined(input as JsonObject));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );
}
