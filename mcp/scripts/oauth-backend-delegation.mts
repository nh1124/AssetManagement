// WP35: the MCP server is the OAuth front door and keeps no state. Registration,
// sign-in and tokens go to the backend; CIMD documents are read only from public
// addresses; Claude Code's document earns a refresh token.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { CODE, SIGN_IN, startFakeBackend } from "./fake-backend.mts";

process.env.APP_ENV = "development";
process.env.JWT_SECRET = "delegation-test-secret-at-least-32-characters";
const {
  clientFromMetadata, getDiscoveryMetadata, isMetadataDocumentClientId, isSpecialUseAddress, metadataCacheMs,
} = await import("../src/auth.js");

// ─── Metadata documents ───────────────────────────────────

const claudeCode = "https://claude.ai/oauth/claude-code-client-metadata";
const document = {
  client_id: claudeCode, client_name: "Claude Code", client_uri: "https://claude.ai",
  redirect_uris: ["http://localhost/callback", "http://127.0.0.1/callback", "http://evil.example/callback"],
  grant_types: ["authorization_code", "refresh_token"], response_types: ["code"], token_endpoint_auth_method: "none",
};
const client = clientFromMetadata(claudeCode, document);
assert.deepEqual(client.grant_types, ["authorization_code", "refresh_token"]);
// Only https and loopback http redirect URIs are kept.
assert.deepEqual(client.redirect_uris, ["http://localhost/callback", "http://127.0.0.1/callback"]);
assert.equal(client.source, "cimd");
assert.deepEqual(clientFromMetadata(claudeCode, { ...document, grant_types: undefined }).grant_types, ["authorization_code"]);
assert.throws(() => clientFromMetadata(claudeCode, { ...document, client_id: "https://claude.ai/other" }), /client_id mismatch/);
assert.throws(() => clientFromMetadata(claudeCode, { ...document, redirect_uris: ["http://evil.example/cb"] }), /redirect_uris/);

for (const id of [claudeCode, "https://app.example/client.json"]) assert.equal(isMetadataDocumentClientId(id), true, id);
for (const id of ["https://app.example/", "https://app.example", "http://app.example/client.json", "mcp_abc", "https://u@app.example/c"]) {
  assert.equal(isMetadataDocumentClientId(id), false, id);
}

assert.equal(metadataCacheMs(undefined), 5 * 60 * 1000);
assert.equal(metadataCacheMs("public, max-age=3600"), 3600 * 1000);
assert.equal(metadataCacheMs("max-age=1"), 60 * 1000);
assert.equal(metadataCacheMs("max-age=999999"), 24 * 60 * 60 * 1000);
assert.equal(metadataCacheMs("no-store"), 0);

// SSRF: a document is never fetched from a special-use address (CIMD §8.6).
for (const address of ["127.0.0.1", "10.1.2.3", "172.20.0.5", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
  "::1", "::", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "not an ip"]) {
  assert.equal(isSpecialUseAddress(address), true, address);
}
for (const address of ["160.79.104.10", "8.8.8.8", "2606:4700::6810:84e5"]) assert.equal(isSpecialUseAddress(address), false, address);

assert.equal(getDiscoveryMetadata("http://localhost:13000").authorization_response_iss_parameter_supported, true);

// ─── The running server, against a fake backend ───────────

const backend = await startFakeBackend();
const port = String(36123 + Math.floor(Math.random() * 1000));
const base = `http://127.0.0.1:${port}`;
const self = `http://localhost:${port}`;
const child = spawn(process.execPath, ["--import", "tsx", "src/server-http.ts"], {
  cwd: new URL("..", import.meta.url),
  env: { ...process.env, PORT: port, BASE_URL: self, BACKEND_URL: backend.url },
  stdio: ["ignore", "ignore", "pipe"],
});
let stderr = "";
child.stderr.on("data", chunk => { stderr += chunk.toString(); });

try {
  let ready = false;
  for (let attempt = 0; attempt < 100 && !ready; attempt++) {
    try { ready = (await fetch(`${base}/health`)).ok; } catch { await sleep(100); }
  }
  assert(ready, `server did not start: ${stderr}`);

  // A request without a token is pointed at the protected resource metadata.
  const unauthorized = await fetch(`${base}/mcp`, { method: "POST" });
  assert.equal(unauthorized.status, 401);
  assert.match(unauthorized.headers.get("www-authenticate") ?? "", /resource_metadata="http:\/\/localhost:\d+\/\.well-known\/oauth-protected-resource"/);

  // Registration is the backend's.
  const registered = await fetch(`${base}/register`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_name: "Codex", redirect_uris: ["http://127.0.0.1/callback"], grant_types: ["authorization_code", "refresh_token"] }),
  });
  assert.equal(registered.status, 201);
  const { client_id } = await registered.json() as { client_id: string };
  assert.deepEqual(backend.requests.at(-1), {
    method: "POST", path: "/auth/mcp/clients",
    body: { client_name: "Codex", redirect_uris: ["http://127.0.0.1/callback"], grant_types: ["authorization_code", "refresh_token"] },
  });

  const params = { response_type: "code", client_id, redirect_uri: "http://127.0.0.1:45789/callback",
    code_challenge: "challenge", code_challenge_method: "S256", state: "xyz" };
  const page = await fetch(`${base}/authorize?${new URLSearchParams(params)}`);
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.match(html, /戻り先: <strong>127\.0\.0\.1:45789<\/strong>/);
  assert.match(html, /このコンピューターで動いているアプリに許可します/);

  const authorize = (fields: Record<string, string>) => fetch(`${base}/authorize`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ ...params, ...fields }), redirect: "manual",
  });
  const refused = await authorize({ username: SIGN_IN.username, password: "wrong", code: SIGN_IN.factor });
  assert.equal(refused.status, 401);
  assert.match(await refused.text(), /ユーザー名、パスワードまたは認証コードが正しくありません/);
  const unfinished = await authorize({ username: "setup", password: "x", code: "000000" });
  assert.equal(unfinished.status, 403);
  assert.match(await unfinished.text(), /認証アプリを設定してください/);

  const granted = await authorize({ username: SIGN_IN.username, password: SIGN_IN.password, code: SIGN_IN.factor });
  assert.equal(granted.status, 302);
  const location = new URL(granted.headers.get("location") ?? "");
  assert.equal(`${location.origin}${location.pathname}`, "http://127.0.0.1:45789/callback");
  assert.equal(location.searchParams.get("code"), CODE);
  assert.equal(location.searchParams.get("state"), "xyz");
  assert.equal(location.searchParams.get("iss"), self);
  const signIn = backend.requests.at(-1)!;
  assert.equal(signIn.path, "/auth/mcp/authorize");
  assert.equal(signIn.body.client_source, "dcr");
  assert.equal(signIn.body.allow_refresh, true);
  assert.equal(signIn.body.issuer, self);
  assert.equal(signIn.body.resource, `${self}/mcp`);
  assert.equal(signIn.body.factor, SIGN_IN.factor);

  // The token endpoint relays the backend's answer and is never cached.
  const token = (fields: Record<string, string>) => fetch(`${base}/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(fields),
  });
  const tokens = await token({ grant_type: "authorization_code", client_id, code: CODE,
    redirect_uri: params.redirect_uri, code_verifier: "verifier" });
  assert.equal(tokens.status, 200);
  assert.equal(tokens.headers.get("cache-control"), "no-store");
  assert.equal((await tokens.json() as { refresh_token: string }).refresh_token, "refresh-from-backend");
  assert.deepEqual(await (await token({ grant_type: "refresh_token", client_id, refresh_token: "stale" })).json(), { error: "invalid_grant" });
  const before = backend.requests.length;
  assert.deepEqual(await (await token({ grant_type: "authorization_code", code: CODE })).json(), { error: "invalid_request" });
  assert.deepEqual(await (await token({ grant_type: "password", client_id })).json(), { error: "unsupported_grant_type" });
  assert.equal(backend.requests.length, before, "malformed token requests never reach the backend");

  // A metadata document on a private address is never fetched: localhost is refused.
  const local = await fetch(`${base}/authorize?${new URLSearchParams({ ...params, client_id: "https://localhost/client.json" })}`);
  assert.equal(local.status, 400);
  assert.deepEqual(await local.json(), { error: "invalid_client" });
  // An unknown registration id is refused by the backend's lookup.
  const unknown = await fetch(`${base}/authorize?${new URLSearchParams({ ...params, client_id: `mcp_${"0".repeat(32)}` })}`);
  assert.deepEqual(await unknown.json(), { error: "invalid_client" });

  // Open registration is limited to 20 a minute.
  const statuses: number[] = [];
  for (let attempt = 0; attempt < 20; attempt++) {
    statuses.push((await fetch(`${base}/register`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ redirect_uris: ["http://localhost/callback"] }),
    })).status);
  }
  assert.equal(statuses.filter(status => status === 201).length, 19);
  assert.equal(statuses.at(-1), 429);
} finally {
  child.kill();
  await backend.close();
}

console.log("OAuth front door: registration, sign-in and tokens go to the backend; CIMD is public-only and keeps refresh_token");
