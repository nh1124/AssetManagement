import assert from "node:assert/strict";

process.env.BACKEND_URL = "http://backend.test";
process.env.BACKEND_USERNAME = "test-user";
process.env.BACKEND_PASSWORD = "test-password";

// Every backend call answers with `backendReply` (undefined: 204 No Content); sign-in answers with a token.
let backendReply: unknown = [];
const requested: string[] = [];
globalThis.fetch = async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
  const url = String(input);
  if (url.endsWith("/auth/login")) return Response.json({ access_token: "token" });
  requested.push(`${init?.method ?? "GET"} ${url}`);
  return backendReply === undefined ? new Response(null, { status: 204 }) : Response.json(backendReply);
};

const { Client } = await import("@modelcontextprotocol/sdk/client/index.js");
const { InMemoryTransport } = await import("@modelcontextprotocol/sdk/inMemory.js");
const { buildMcpServer } = await import("../src/server.js");
const { toStructured } = await import("../src/utils.js");

assert.deepEqual(toStructured([{ id: 1 }]), { items: [{ id: 1 }] });
assert.deepEqual(toStructured({ id: 1 }), { id: 1 });
assert.deepEqual(toStructured(null), {});
assert.deepEqual(toStructured(undefined), {});
assert.deepEqual(toStructured(3), { value: 3 });

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await buildMcpServer().connect(serverTransport);
const client = new Client({ name: "structured-content-test", version: "0.0.1" });
await client.connect(clientTransport);

// The smallest arguments each tool's input schema accepts.
type Schema = {
  type?: string | string[]; properties?: Record<string, Schema>; required?: string[]; items?: Schema; $ref?: string;
  enum?: unknown[]; const?: unknown; anyOf?: Schema[]; minItems?: number; minimum?: number; maximum?: number;
  minLength?: number; pattern?: string; format?: string;
};
function sample(schema: Schema, root: Schema = schema): unknown {
  if (schema.$ref?.startsWith("#/")) {
    // The SDK writes a repeated field as a pointer to its first use ("#/properties/capsule_id").
    const target = schema.$ref.slice(2).split("/").reduce<unknown>((node, key) => (node as Record<string, unknown>)[key], root);
    return sample(target as Schema, root);
  }
  if (schema.const !== undefined) return schema.const;
  if (schema.enum) return schema.enum[0];
  if (schema.anyOf) return sample(schema.anyOf.find(option => option.type !== "null") ?? schema.anyOf[0], root);
  const type = Array.isArray(schema.type) ? schema.type.find(t => t !== "null") : schema.type;
  switch (type) {
    case "object":
      return Object.fromEntries((schema.required ?? []).map(key => [key, sample(schema.properties?.[key] ?? {}, root)]));
    case "array":
      return Array.from({ length: Math.max(schema.minItems ?? 1, 1) }, () => sample(schema.items ?? {}, root));
    case "integer":
    case "number":
      return Math.min(Math.max(schema.minimum ?? 1, 1), schema.maximum ?? Number.MAX_SAFE_INTEGER);
    case "boolean":
      return false;
    case "string": {
      const pattern = schema.pattern ?? "";
      if (schema.format === "date" || pattern.includes("\\d{2}-\\d{2}")) return "2026-01-01";
      if (pattern.includes("\\d{4}-")) return "2026-01";
      if (pattern.includes("{3}")) return "USD";
      return "x".repeat(Math.max(schema.minLength ?? 1, 1));
    }
    default:
      return null;
  }
}

// The tools whose endpoints answer 204 No Content (DELETE /products/{id}, DELETE /registry-entries/{id}).
const noContentTools = new Set(["products_delete", "auto_transactions_delete"]);

const { tools } = await client.listTools();
const unexercised: string[] = [];
const malformed: string[] = [];
for (const tool of tools) {
  const args = sample(tool.inputSchema as Schema) as Record<string, unknown>;
  for (const reply of noContentTools.has(tool.name) ? [[{ id: 1 }], null, undefined] : [[{ id: 1 }], null]) {
    backendReply = reply;
    const label = `${tool.name} with the backend returning ${JSON.stringify(reply) ?? "nothing"}`;
    let result;
    try {
      result = await client.callTool({ name: tool.name, arguments: args });
    } catch (err) {
      // The server refuses a result that breaks CallToolResultSchema with an McpError.
      malformed.push(`${label}: ${(err as Error).message.split("\n")[0]}`);
      continue;
    }
    const text = JSON.stringify(result.content);
    if (result.isError && /validation error/i.test(text)) { unexercised.push(`${tool.name}: ${text.slice(0, 200)}`); break; }
    const structured = result.structuredContent;
    if (structured !== undefined && (structured === null || typeof structured !== "object" || Array.isArray(structured))) {
      malformed.push(`${label}: structuredContent ${JSON.stringify(structured)}`);
    }
  }
}
assert.deepEqual(unexercised, [], "every tool should be called with arguments its schema accepts");
assert.deepEqual(malformed, [], "every tool result should pass CallToolResultSchema");

// The call that failed on 2026-10-24.
backendReply = [{ id: 7, name: "event", target_amount: 1000 }];
requested.length = 0;
const lifeEvents = await client.callTool({ name: "life_events_list", arguments: { scenario_id: 3 } });
assert.deepEqual(requested, ["GET http://backend.test/life-events/with-progress?scenario_id=3"]);
assert.deepEqual(lifeEvents.structuredContent, { items: [{ id: 7, name: "event", target_amount: 1000 }] });

await client.close();
console.log(`all ${tools.length} tool results pass CallToolResultSchema when the backend returns a list or null`);
