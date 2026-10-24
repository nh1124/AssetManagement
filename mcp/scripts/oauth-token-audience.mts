import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";

const secret = "audience-test-secret-at-least-32-characters";
process.env.APP_ENV = "development";
process.env.JWT_SECRET = secret;
process.env.MCP_ACCEPTED_RESOURCES = " https://mcp-b.example/mcp/ , ";

const {
  EXTRA_ACCEPTED_RESOURCES, acceptedResources, createAuthCode, exchangeCodeForTokens, isResourceIn,
  normalizeResource, ownResources, tokenAudienceAccepted,
} = await import("../src/auth.js");

// ─── Matching rules ───────────────────────────────────────

assert.deepEqual(EXTRA_ACCEPTED_RESOURCES, ["https://mcp-b.example/mcp"]);
assert.equal(normalizeResource("http://LOCALHOST:13000/mcp/"), "http://localhost:13000/mcp");
assert.equal(normalizeResource("https://mcp.example:443/mcp"), "https://mcp.example/mcp");
for (const value of ["mcp.example/mcp", "ftp://mcp.example/mcp", "http://user@localhost:13000/mcp", "http://localhost:13000/mcp#x", ""]) {
  assert.equal(normalizeResource(value), null, value);
}

const own = ownResources("http://localhost:13000/mcp");
assert.deepEqual(own, ["http://localhost:13000/mcp", "http://localhost:13000"]);
assert.deepEqual(acceptedResources("http://localhost:13000/mcp", []), own);
const accepted = acceptedResources("http://localhost:13000/mcp");
assert.deepEqual(accepted, [...own, "https://mcp-b.example/mcp"]);

for (const aud of [
  ["http://localhost:13000/mcp", "asset-management-backend"],
  "http://localhost:13000/",
  ["asset-management-backend", "https://mcp-b.example/mcp"],
]) {
  assert.equal(tokenAudienceAccepted(aud, accepted), true, JSON.stringify(aud));
}
for (const aud of [
  undefined,
  [],
  ["asset-management-backend"],
  ["http://localhost:13001/mcp"],
  ["https://localhost:13000/mcp"],
  ["http://localhost:13000/mcp/extra"],
  ["https://mcp-c.example/mcp"],
]) {
  assert.equal(tokenAudienceAccepted(aud, accepted), false, JSON.stringify(aud));
}
// Without the list, the other server is closed again.
assert.equal(tokenAudienceAccepted(["https://mcp-b.example/mcp"], acceptedResources("http://localhost:13000/mcp", [])), false);
// /authorize issues only for this server, never for a listed one.
assert.equal(isResourceIn("http://localhost:13000/mcp/", own), true);
assert.equal(isResourceIn("https://mcp-b.example/mcp", own), false);

// ─── The running server ───────────────────────────────────

const mcpDir = new URL("..", import.meta.url);

function startServer(env: Record<string, string>) {
  const child = spawn(process.execPath, ["--import", "tsx", "src/server-http.ts"], {
    cwd: mcpDir,
    env: { ...process.env, BACKEND_URL: "http://127.0.0.1:9", ...env },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", chunk => { stderr += chunk.toString(); });
  return { child, stderr: () => stderr };
}

// A mistyped address stops the server instead of being dropped.
{
  const { child, stderr } = startServer({ PORT: "0", MCP_ACCEPTED_RESOURCES: "mcp-b.example/mcp" });
  const code = await new Promise<number | null>(resolve => child.on("exit", resolve));
  assert.notEqual(code, 0);
  assert.match(stderr(), /MCP_ACCEPTED_RESOURCES entry is not an http\(s\) URL: mcp-b\.example\/mcp/);
}

const port = String(35123 + Math.floor(Math.random() * 1000));
const base = `http://127.0.0.1:${port}`;
const self = `http://localhost:${port}`;
const server = startServer({ PORT: port, BASE_URL: self, MCP_ACCEPTED_RESOURCES: "https://mcp-b.example/mcp" });

function tokenFor(resource: string): string {
  const verifier = crypto.randomBytes(32).toString("base64url");
  const code = createAuthCode({
    client_id: "audience-client", redirect_uri: "http://localhost/callback",
    code_challenge: crypto.createHash("sha256").update(verifier).digest("base64url"),
    code_challenge_method: "S256", resource, allow_refresh_token: false,
    username: "tester", backend_client_id: 1, issuer: self, auth_time_ms: Date.now(),
  });
  const tokens = exchangeCodeForTokens({ code, client_id: "audience-client", redirect_uri: "http://localhost/callback",
    code_verifier: verifier, resource, canonical_resource: resource });
  assert(tokens);
  return tokens.access_token;
}

try {
  let ready = false;
  for (let attempt = 0; attempt < 100 && !ready; attempt++) {
    try { ready = (await fetch(`${base}/health`)).ok; } catch { await sleep(100); }
  }
  assert(ready, `server did not start: ${server.stderr()}`);

  // GET answers 405 once the token is accepted, 401 when it is refused.
  const get = (path: string, token: string) => fetch(`${base}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  for (const resource of [`${self}/mcp`, `${self}/mcp/`, self, "https://mcp-b.example/mcp"]) {
    for (const path of ["/mcp", "/"]) {
      assert.equal((await get(path, tokenFor(resource))).status, 405, `${resource} on ${path}`);
    }
  }
  for (const resource of ["https://mcp-c.example/mcp", `http://localhost:${Number(port) + 1}/mcp`, ""]) {
    const refused = await get("/mcp", tokenFor(resource));
    assert.equal(refused.status, 401, resource);
    assert.deepEqual(await refused.json(), { error: "invalid_token" });
    assert.match(refused.headers.get("www-authenticate") ?? "", /token not issued for this MCP server/);
  }

  const registration = await fetch(`${base}/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_name: "audience test", redirect_uris: ["http://localhost/callback"] }),
  });
  const { client_id } = await registration.json() as { client_id: string };
  const params = (resource?: string) => ({
    response_type: "code", client_id, redirect_uri: "http://localhost:45789/callback",
    code_challenge: "challenge", code_challenge_method: "S256", ...(resource === undefined ? {} : { resource }),
  });
  const authorizeGet = (resource?: string) => fetch(`${base}/authorize?${new URLSearchParams(params(resource))}`);
  const authorizePost = (resource?: string) => fetch(`${base}/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ ...params(resource), username: "nobody", password: "wrong", code: "000000" }),
  });

  for (const resource of [undefined, `${self}/mcp`, `${self}/mcp/`, self]) {
    assert.equal((await authorizeGet(resource)).status, 200, String(resource));
    // A refused sign-in re-renders the form, so the resource passed the check.
    assert.equal((await authorizePost(resource)).status, 401, String(resource));
  }
  for (const resource of ["https://mcp-b.example/mcp", "https://evil.example/mcp", "not a url"]) {
    for (const response of [await authorizeGet(resource), await authorizePost(resource)]) {
      assert.equal(response.status, 400, resource);
      assert.deepEqual(await response.json(), { error: "invalid_target" });
    }
  }
} finally {
  server.child.kill();
}

console.log("Token audience: only this server's resource and the listed ones are accepted, /authorize issues only for this server");
