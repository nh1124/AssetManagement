// ============================================================
// Asset Management MCP Server - Entry Point (stdio)
// ============================================================

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerAccountTools } from "./tools/accounts.js";
import { registerCapsuleTools } from "./tools/capsules.js";
import { registerLifeEventTools } from "./tools/life-events.js";
import { registerAnalysisTools } from "./tools/analysis.js";
import { registerTransactionTools } from "./tools/transactions.js";
import { registerCalculatorTools } from "./tools/calculator.js";

const server = new McpServer({
  name: "asset-management",
  version: "1.0.0"
});

registerAccountTools(server);
registerCapsuleTools(server);
registerLifeEventTools(server);
registerAnalysisTools(server);
registerTransactionTools(server);
registerCalculatorTools(server);

const transport = new StdioServerTransport();
await server.connect(transport);
