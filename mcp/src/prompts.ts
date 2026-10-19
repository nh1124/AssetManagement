// ============================================================
// MCP prompts
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerPrompts(server: McpServer): void {
  server.registerPrompt(
    "monthly-finance-review",
    {
      title: "Monthly finance review",
      description: "Guide an assistant through reviewing a monthly report and turning it into next actions.",
      argsSchema: {
        period: z.string().regex(/^\d{4}-\d{2}$/).describe("Target period, YYYY-MM"),
      },
    },
    async ({ period }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Review ${period} using reports_monthly, analysis_profit_loss, analysis_variance, and actions_list. ` +
              "Summarize the financial state, call out material changes, and propose concrete next actions. " +
              "Do not apply write tools unless explicitly asked.",
          },
        },
      ],
    }),
  );

  server.registerPrompt(
    "goal-check",
    {
      title: "Goal check",
      description: "Review the goal scenario, its simulation and the plan before suggesting changes.",
      argsSchema: {
        period: z.string().optional().describe("Month to compare with the plan, YYYY-MM"),
      },
    },
    async ({ period }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              "Inspect the goal using life_scenarios_list, life_scenarios_simulate for the goal scenario and life_events_list, " +
              `then goal_plan_check${period ? ` for ${period}` : ""}. Identify events unlikely to happen or be affordable, ` +
              "accounts whose plan falls short of the 積立設定, and preview with goal_plan_preview before any goal_plan_apply.",
          },
        },
      ],
    }),
  );
}
