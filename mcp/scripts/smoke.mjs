import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const cwd = process.cwd();

async function smokeStdio() {
  const client = new Client({ name: "asset-management-smoke", version: "0.0.1" });
  const transport = new StdioClientTransport({
    command: "node",
    args: ["dist/index.js"],
    cwd,
  });
  await client.connect(transport);

  const { tools } = await client.listTools();
  if (tools.length < 30) {
    throw new Error(`Expected at least 30 tools, found ${tools.length}`);
  }

  const { resources } = await client.listResources();
  if (resources.length < 2) {
    throw new Error(`Expected at least 2 resources, found ${resources.length}`);
  }

  const { prompts } = await client.listPrompts();
  if (prompts.length < 2) {
    throw new Error(`Expected at least 2 prompts, found ${prompts.length}`);
  }

  const result = await client.callTool({
    name: "calc_future_value",
    arguments: { monthly_amount: 10000, annual_rate_pct: 5, years: 10 },
  });
  if (result.structuredContent?.future_value !== 1559293) {
    throw new Error("calc_future_value returned an unexpected result");
  }

  await client.close();
  console.log(`stdio ok: ${tools.length} tools, ${resources.length} resources, ${prompts.length} prompts`);
}

async function smokeHttp() {
  const port = String(33123 + Math.floor(Math.random() * 1000));
  const child = spawn("node", ["dist/server-http.js"], {
    cwd,
    env: {
      ...process.env,
      PORT: port,
      BASE_URL: `http://localhost:${port}`,
      MCP_PASSWORD: process.env.MCP_PASSWORD || "smoke-password",
      JWT_SECRET: process.env.JWT_SECRET || "smoke-secret-at-least-32-characters",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
  });

  try {
    for (let i = 0; i < 25; i += 1) {
      if (child.exitCode !== null) {
        throw new Error(`HTTP server exited early with code ${child.exitCode}: ${stderr}`);
      }
      try {
        const res = await fetch(`http://localhost:${port}/health`);
        if (res.ok) {
          const body = await res.json();
          if (body.status !== "ok") {
            throw new Error(`Unexpected health body: ${JSON.stringify(body)}`);
          }
          console.log(`http ok: ${body.server} on ${port}`);
          return;
        }
      } catch {
        await sleep(200);
      }
    }
    throw new Error(`HTTP health did not become ready: ${stderr}`);
  } finally {
    child.kill();
  }
}

await smokeStdio();
await smokeHttp();
