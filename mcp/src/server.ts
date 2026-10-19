// ============================================================
// Shared MCP server factory
// ============================================================

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { registerAccountTools } from "./tools/accounts.js";
import { registerActionTools } from "./tools/actions.js";
import { registerAiChangeRequestTools } from "./tools/ai-change-requests.js";
import { registerAiTools } from "./tools/ai.js";
import { registerAnalysisTools } from "./tools/analysis.js";
import { registerCalculatorTools } from "./tools/calculator.js";
import { registerCapsuleTools } from "./tools/capsules.js";
import { registerClientTools } from "./tools/clients.js";
import { registerDataTransferTools } from "./tools/data-transfer.js";
import { registerExchangeRateTools } from "./tools/exchange-rates.js";
import { registerGuidanceTools } from "./tools/guidance.js";
import { registerLifeEventTools } from "./tools/life-events.js";
import { registerMonthlyPlanningTools } from "./tools/monthly-planning.js";
import { registerPeriodReviewTools } from "./tools/period-reviews.js";
import { registerProductTools } from "./tools/products.js";
import { registerAutoTransactionTools } from "./tools/auto-transactions.js";
import { registerReportTools } from "./tools/reports.js";
import { registerRoadmapTools } from "./tools/roadmap.js";
import { registerSimulationTools } from "./tools/simulation.js";
import { registerStrategyTools } from "./tools/strategy.js";
import { registerTransactionBatchTools } from "./tools/transaction-batches.js";
import { registerTransactionTools } from "./tools/transactions.js";
import { registerPrompts } from "./prompts.js";
import { registerResources } from "./resources.js";

export function buildMcpServer(): McpServer {
  const server = new McpServer({
    name: "asset-management",
    version: "1.0.0",
  });

  registerAccountTools(server);
  registerGuidanceTools(server);
  registerCapsuleTools(server);
  registerLifeEventTools(server);
  registerAnalysisTools(server);
  registerTransactionTools(server);
  registerTransactionBatchTools(server);
  registerCalculatorTools(server);
  registerReportTools(server);
  registerPeriodReviewTools(server);
  registerActionTools(server);
  registerAutoTransactionTools(server);
  registerRoadmapTools(server);
  registerStrategyTools(server);
  registerProductTools(server);
  registerMonthlyPlanningTools(server);
  registerSimulationTools(server);
  registerExchangeRateTools(server);
  registerDataTransferTools(server);
  registerClientTools(server);
  registerAiTools(server);
  registerAiChangeRequestTools(server);
  registerResources(server);
  registerPrompts(server);

  return server;
}
