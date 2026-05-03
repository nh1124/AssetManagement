// ============================================================
// Asset Management MCP Server - Entry Point (stdio)
// ============================================================

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { buildMcpServer } from "./server.js";

const server = buildMcpServer();

const transport = new StdioServerTransport();
await server.connect(transport);
