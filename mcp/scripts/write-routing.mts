// The MCP server does not read the write mode (WP36): every write goes to the backend, and
// the tools a change request can carry turn the backend's "needs approval" refusal into one.
import assert from "node:assert/strict";

process.env.BACKEND_URL = "http://backend.test";
process.env.BACKEND_USERNAME = "test-user";
process.env.BACKEND_PASSWORD = "test-password";

type Reply = { status: number; body: unknown };
// "METHOD /path" -> the reply; anything else answers 404.
let replies = new Map<string, Reply>();
const requested: Array<{ call: string; body: unknown }> = [];
globalThis.fetch = async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
  const url = new URL(String(input));
  if (url.pathname === "/auth/login") return Response.json({ access_token: "token" });
  const call = `${init?.method ?? "GET"} ${url.pathname}`;
  requested.push({ call, body: init?.body ? JSON.parse(String(init.body)) : undefined });
  const reply = replies.get(call) ?? { status: 404, body: { detail: "Not Found" } };
  return Response.json(reply.body, { status: reply.status });
};

const { Client } = await import("@modelcontextprotocol/sdk/client/index.js");
const { InMemoryTransport } = await import("@modelcontextprotocol/sdk/inMemory.js");
const { buildMcpServer } = await import("../src/server.js");

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await buildMcpServer().connect(serverTransport);
const client = new Client({ name: "write-routing-test", version: "0.0.1" });
await client.connect(clientTransport);

const refused = (reason: string): Reply => ({
  status: 403,
  body: { detail: { error: "ai_operation_refused", reason, message: `refused: ${reason}` } },
});
const changeRequest: Reply = { status: 200, body: { id: 7, status: "pending" } };

async function run(name: string, args: Record<string, unknown>, routes: Record<string, Reply>) {
  replies = new Map(Object.entries(routes));
  requested.length = 0;
  const result = await client.callTool({ name, arguments: args });
  const text = (result.content as Array<{ text?: string }>).map((part) => part.text ?? "").join("\n");
  return { text, calls: requested.map(({ call }) => call), bodies: requested.map(({ body }) => body) };
}

const transaction = { date: "2026-10-24", description: "lunch", amount: 1200, from_account_id: 1, to_account_id: 2 };

// Allowed: one write, nothing asked first.
let outcome = await run("transactions_create", transaction, { "POST /transactions/": { status: 200, body: { id: 1 } } });
assert.deepEqual(outcome.calls, ["POST /transactions/"]);
assert.match(outcome.text, /Direct write/);

// The backend wants approval (either reason): the tool creates the change request.
for (const reason of ["change_request_mode", "operation_needs_approval"]) {
  outcome = await run("transactions_create", transaction, {
    "POST /transactions/": refused(reason), "POST /ai/change-requests": changeRequest,
  });
  assert.deepEqual(outcome.calls, ["POST /transactions/", "POST /ai/change-requests"], reason);
  assert.deepEqual(outcome.bodies[1], { resource: "transactions", action: "create", input_payload: transaction, status: "pending" });
  assert.match(outcome.text, /Created approval request #7; no direct write was applied/);
}

// Denied: the backend's message reaches the AI; no change request.
outcome = await run("transactions_create", transaction, { "POST /transactions/": refused("operation_denied") });
assert.deepEqual(outcome.calls, ["POST /transactions/"]);
assert.match(outcome.text, /403: .*refused: operation_denied/);

// A write no change request carries: the backend refuses it, the AI reads why.
outcome = await run("transactions_update", { id: 5, amount: 1 }, { "PUT /transactions/5": refused("change_request_mode") });
assert.deepEqual(outcome.calls, ["PUT /transactions/5"]);
assert.match(outcome.text, /refused: change_request_mode/);
outcome = await run("auto_transactions_delete", { id: 3 }, { "DELETE /auto-transactions/3": refused("change_request_mode") });
assert.deepEqual(outcome.calls, ["DELETE /auto-transactions/3"]);

// Automatic transactions: an update becomes a change request on its target.
const schedule = { name: "rent", amount: 80000, source_account_id: 1, destination_account_id: 2, start_date: "2026-11-01" };
outcome = await run("auto_transactions_update", { id: 9, ...schedule }, {
  "PUT /auto-transactions/9": refused("operation_needs_approval"), "POST /ai/change-requests": changeRequest,
});
assert.deepEqual(outcome.bodies[1], { resource: "auto_transactions", action: "update", target_ref: { id: 9 }, input_payload: schedule, status: "pending" });

// Plan lines: new lines are written, refused updates become one change request each.
outcome = await run("monthly_plan_lines_save_batch", { lines: [
  { target_period: "2026-11", line_type: "expense", account_id: 2, amount: 100 },
  { id: 11, target_period: "2026-11", line_type: "expense", amount: 200 },
  { id: 12, target_period: "2026-11", line_type: "expense", amount: 300 },
] }, {
  "POST /budget-plans/lines": { status: 200, body: [{ id: 13 }] },
  "PUT /budget-plans/lines/batch": refused("operation_needs_approval"),
  "POST /ai/change-requests": changeRequest,
});
assert.deepEqual(outcome.calls, ["POST /budget-plans/lines", "PUT /budget-plans/lines/batch", "POST /ai/change-requests", "POST /ai/change-requests"]);
assert.deepEqual(outcome.bodies.slice(2).map((body) => (body as { target_ref: unknown }).target_ref), [{ id: 11 }, { id: 12 }]);
assert.match(outcome.text, /Created monthly plan lines/);

// In change-request mode new lines are refused before any update is tried.
outcome = await run("monthly_plan_lines_save_batch", { lines: [
  { target_period: "2026-11", line_type: "expense", account_id: 2, amount: 100 },
  { id: 11, target_period: "2026-11", line_type: "expense", amount: 200 },
] }, { "POST /budget-plans/lines": refused("change_request_mode") });
assert.deepEqual(outcome.calls, ["POST /budget-plans/lines"]);
assert.match(outcome.text, /refused: change_request_mode/);

await client.close();
console.log("write routing: writes go to the backend unchecked; approval refusals become change requests, other refusals reach the AI");
