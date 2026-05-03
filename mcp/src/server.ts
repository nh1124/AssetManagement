// ============================================================
// Shared MCP server factory
// ============================================================

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { registerAccountTools } from "./tools/accounts.js";
import { registerActionTools } from "./tools/actions.js";
import { registerAnalysisTools } from "./tools/analysis.js";
import { registerCalculatorTools } from "./tools/calculator.js";
import { registerCapsuleTools } from "./tools/capsules.js";
import { registerLifeEventTools } from "./tools/life-events.js";
import { registerPeriodReviewTools } from "./tools/period-reviews.js";
import { registerProductTools } from "./tools/products.js";
import { registerRecurringTools } from "./tools/recurring.js";
import { registerReportTools } from "./tools/reports.js";
import { registerRoadmapTools } from "./tools/roadmap.js";
import { registerTransactionTools } from "./tools/transactions.js";
import { registerPrompts } from "./prompts.js";
import { registerResources } from "./resources.js";

export function buildMcpServer(): McpServer {
  const server = new McpServer({
    name: "asset-management",
    version: "1.0.0",
  });

  registerAccountTools(server);
  registerCapsuleTools(server);
  registerLifeEventTools(server);
  registerAnalysisTools(server);
  registerTransactionTools(server);
  registerCalculatorTools(server);
  registerReportTools(server);
  registerPeriodReviewTools(server);
  registerActionTools(server);
  registerRecurringTools(server);
  registerRoadmapTools(server);
  registerProductTools(server);
  registerResources(server);
  registerPrompts(server);

  return server;
}
