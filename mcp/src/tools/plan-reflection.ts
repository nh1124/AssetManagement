// ============================================================
// 計画への反映: how the goal and the product earmarks are written into the plan
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const settingsSchema = z
  .object({
    enabled: z.boolean().optional().describe("自動反映: rewrite this month and the 11 after it at the start of each month and after a change"),
    goal: z
      .object({
        base: z.enum(["remaining", "goal_setting"]).optional()
          .describe("Goal earmarks: remaining (the target over the months left) or goal_setting (fixed from the 積立設定 since the earmark began)"),
        held: z.enum(["even", "recent"]).optional().describe("What an earmark already holds comes off evenly or from the nearest months"),
        catch_up: z.enum(["even", "recent", "none"]).optional()
          .describe("A shortfall against the schedule (and of 積立 since the settings began) is spread evenly, added to this month, or not caught up"),
      })
      .strict()
      .optional(),
    products: z
      .object({
        enabled: z.boolean().optional().describe("Write rows for earmarks with linked products"),
        base: z.enum(["remaining", "saved"]).optional().describe("remaining (to the replacement month) or saved (the earmark's monthly amount)"),
        held: z.enum(["even", "recent"]).optional(),
      })
      .strict()
      .optional(),
  })
  .strict();

function reply(label: string, data: unknown) {
  return { content: [{ type: "text" as const, text: `${label}\n${JSON.stringify(data, null, 2)}` }], structuredContent: toStructured(data) };
}

function failed(err: unknown) {
  return { content: [{ type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
}

export function registerPlanReflectionTools(server: McpServer): void {
  server.registerTool("plan_reflection_get", {
    title: "Plan reflection settings and history",
    description: "The settings of 計画への反映 (how the goal and product earmarks are written into the plan, and whether 自動反映 is on), the 12 months a run writes, and the latest runs with what they changed.",
    inputSchema: z.object({}).strict(),
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, async () => {
    try { return reply("Plan reflection:", await api.get<unknown>("/plan/reflection")); } catch (err) { return failed(err); }
  });

  server.registerTool("plan_reflection_preview", {
    title: "Preview the plan reflection",
    description: "What a run would change now (this month and the 11 after it), with the saved settings or the given changes to them. Nothing is saved.",
    inputSchema: settingsSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, async (input) => {
    try { return reply("Plan reflection preview:", await api.post<unknown>("/plan/reflection/preview", input)); } catch (err) { return failed(err); }
  });

  server.registerTool("plan_reflection_settings_update", {
    title: "Change the plan reflection settings",
    description: "Saves the settings (fields left out keep their value). With 自動反映 on, the plan is rewritten at once. Preview first and ask the user.",
    inputSchema: settingsSchema,
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
  }, async (input) => {
    try { return reply("Saved:", await api.put<unknown>("/plan/reflection/settings", input)); } catch (err) { return failed(err); }
  });

  server.registerTool("plan_reflection_run", {
    title: "Reflect the goal into the plan now",
    description: "今すぐ反映: rewrites the goal's rows and the product earmarks' rows for this month and the 11 after it, as the settings say. Past months and the user's records are not touched. Preview first and ask the user.",
    inputSchema: z.object({}).strict(),
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  }, async () => {
    try { return reply("Reflected:", await api.post<unknown>("/plan/reflection/run", {})); } catch (err) { return failed(err); }
  });
}
