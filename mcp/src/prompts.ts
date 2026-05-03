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
    "goal-roadmap-check",
    {
      title: "Goal roadmap check",
      description: "Review goals, milestones, and roadmap projection before suggesting plan changes.",
      argsSchema: {
        years: z.string().optional().describe("Projection years to inspect"),
      },
    },
    async ({ years }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Inspect the roadmap using life_events_list, roadmap_projection${years ? ` with years=${years}` : ""}, ` +
              "and roadmap_milestones_list. Identify risks, missing milestones, and useful simulations. " +
              "Preview generated milestones before applying them.",
          },
        },
      ],
    }),
  );
}
