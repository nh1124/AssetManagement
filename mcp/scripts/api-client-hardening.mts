import assert from "node:assert/strict";

process.env.BACKEND_URL = "http://backend.test";
process.env.BACKEND_USERNAME = "test-user";
process.env.BACKEND_PASSWORD = "test-password";

type FetchCall = { url: string; init?: RequestInit };
const calls: FetchCall[] = [];
let responses: Response[] = [];

globalThis.fetch = async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
  calls.push({ url: String(input), init });
  const response = responses.shift();
  assert(response, `Unexpected fetch: ${String(input)}`);
  return response;
};

const { api } = await import("../src/api-client.js");

responses = [
  Response.json({ access_token: "token-1" }),
  new Response("settings unavailable", { status: 503 }),
];
await assert.rejects(
  api.post("/transactions/", { amount: 1 }),
  /Cannot verify MCP write mode; refusing POST \/transactions\/ \(503\)/,
);
assert.equal(calls.some(({ url }) => url === "http://backend.test/transactions/"), false);

calls.length = 0;
responses = [
  Response.json({ mcp_write_mode: "direct_write" }),
  new Response("expired", { status: 401 }),
  Response.json({ access_token: "token-2" }),
  Response.json({ mcp_write_mode: "direct_write" }),
  new Response("still unauthorized", { status: 401 }),
];
await assert.rejects(
  api.post("/transactions/", { amount: 1 }),
  /401 after one authentication retry/,
);
assert.equal(calls.filter(({ url }) => url === "http://backend.test/transactions/").length, 2);

console.log("api-client hardening checks passed");
