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

const { api, ApiError } = await import("../src/api-client.js");

// A write goes straight to the backend: no write-mode check first (WP36). The backend's
// refusal comes back with its reason and message.
const refusal = {
  detail: {
    error: "ai_operation_refused",
    reason: "change_request_mode",
    message: "Writes go through change requests in this client's settings.",
  },
};
responses = [
  Response.json({ access_token: "token-1" }),
  Response.json(refusal, { status: 403 }),
];
const refused = await api.post("/accounts/", { name: "x" }).then(() => null, (error: unknown) => error);
assert(refused instanceof ApiError);
assert.equal(refused.status, 403);
assert.equal(refused.refusal, "change_request_mode");
assert.match(refused.message, /POST \/accounts\/ -> 403: .*Writes go through change requests/);
assert.deepEqual(calls.map(({ url }) => url), ["http://backend.test/auth/login", "http://backend.test/accounts/"]);

// Other errors carry no refusal.
calls.length = 0;
responses = [new Response("nope", { status: 500 })];
const failed = await api.delete("/accounts/3").then(() => null, (error: unknown) => error);
assert(failed instanceof ApiError);
assert.equal(failed.refusal, undefined);

calls.length = 0;
responses = [
  new Response("expired", { status: 401 }),
  Response.json({ access_token: "token-2" }),
  new Response("still unauthorized", { status: 401 }),
];
await assert.rejects(
  api.post("/transactions/", { amount: 1 }),
  /401 after one authentication retry/,
);
assert.equal(calls.filter(({ url }) => url === "http://backend.test/transactions/").length, 2);
assert.equal(calls.some(({ url }) => url.includes("/ai/execution-settings")), false);

console.log("api-client hardening checks passed");
