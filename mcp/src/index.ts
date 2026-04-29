// ============================================================
// Asset Management MCP Server - Entry Point (stdio)
// ============================================================

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerPortfolioTools } from "./tools/portfolio.js";
import { registerBudgetTools } from "./tools/budget.js";
import { registerCalculatorTools } from "./tools/calculator.js";
import { registerDecisionTools } from "./tools/decisions.js";

const server = new McpServer({
  name: "asset-management",
  version: "1.0.0"
});

registerPortfolioTools(server);
registerBudgetTools(server);
registerCalculatorTools(server);
registerDecisionTools(server);

const transport = new StdioServerTransport();
await server.connect(transport);
