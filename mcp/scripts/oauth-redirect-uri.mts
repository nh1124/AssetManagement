import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import { createAuthCode, exchangeCodeForTokens, isRegisteredRedirectUri } from "../src/auth.js";

// ─── Matching rules (RFC 8252 §7.3) ───────────────────────

// What Claude Code's client metadata document registers.
const claudeCode = ["http://localhost/callback", "http://127.0.0.1/callback"];

const allowed: Array<[string[], string]> = [
  [claudeCode, "http://localhost/callback"],
  [claudeCode, "http://localhost:45789/callback"],
  [claudeCode, "http://127.0.0.1:5555/callback"],
  [claudeCode, "http://localhost:65535/callback"],
  [["http://[::1]/callback"], "http://[::1]:45789/callback"],
  // A registered port does not pin the port either.
  [["http://localhost:45789/callback"], "http://localhost:3000/callback"],
  [["http://localhost/cb?app=x"], "http://localhost:3000/cb?app=x"],
  // Everything else is still an exact match.
  [["https://claude.ai/api/mcp/auth_callback"], "https://claude.ai/api/mcp/auth_callback"],
];
for (const [registered, requested] of allowed) {
  assert.equal(isRegisteredRedirectUri(registered, requested), true, `should allow ${requested}`);
}

const refused: Array<[string[], string]> = [
  [claudeCode, "http://localhost:45789/other"],
  [claudeCode, "http://localhost:45789/callback/"],
  [claudeCode, "http://localhost:45789/callback?x=1"],
  [claudeCode, "http://localhost:45789/callback#x"],
  [claudeCode, "http://localhost:0/callback"],
  [claudeCode, "http://localhost:065/callback"],
  [claudeCode, "http://localhost:65536/callback"],
  [claudeCode, "http://localhost:/callback"],
  // The host must be the registered one, spelled the same way.
  [["http://localhost/callback"], "http://127.0.0.1:45789/callback"],
  [claudeCode, "http://[::1]:45789/callback"],
  [claudeCode, "http://127.0.0.2:45789/callback"],
  [claudeCode, "http://LOCALHOST:45789/callback"],
  [claudeCode, "http://localhost.evil.example:45789/callback"],
  [claudeCode, "http://localhost:45789@evil.example/callback"],
  [claudeCode, "http://user@localhost:45789/callback"],
  [claudeCode, "http://evil.example/callback"],
  // Only plain http on loopback ignores the port.
  [claudeCode, "https://localhost:45789/callback"],
  [["https://localhost/callback"], "https://localhost:8443/callback"],
  [["http://evil.example/callback"], "http://evil.example:8080/callback"],
  [["https://claude.ai/api/mcp/auth_callback"], "https://claude.ai:443/api/mcp/auth_callback"],
  [[], "http://localhost:45789/callback"],
];
for (const [registered, requested] of refused) {
  assert.equal(isRegisteredRedirectUri(registered, requested), false, `should refuse ${requested}`);
}

// The token request must repeat the redirect URI of the authorize request
// exactly (RFC 6749 §4.1.3), port included.
const verifier = crypto.randomBytes(32).toString("base64url");
const resource = "http://localhost:13000/mcp";
const authCode = () => createAuthCode({
  client_id: "redirect-client", redirect_uri: "http://localhost:45789/callback",
  code_challenge: crypto.createHash("sha256").update(verifier).digest("base64url"),
  code_challenge_method: "S256", resource, allow_refresh_token: false,
  username: "tester", backend_client_id: 1, issuer: "http://localhost:13000", auth_time_ms: Date.now(),
});
assert.equal(exchangeCodeForTokens({ code: authCode(), client_id: "redirect-client",
  redirect_uri: "http://localhost:1234/callback", code_verifier: verifier, resource, canonical_resource: resource }), null);
assert(exchangeCodeForTokens({ code: authCode(), client_id: "redirect-client",
  redirect_uri: "http://localhost:45789/callback", code_verifier: verifier, resource, canonical_resource: resource }));

// ─── Both /authorize handlers use the rule ────────────────

const port = String(34123 + Math.floor(Math.random() * 1000));
const base = `http://127.0.0.1:${port}`;
const child = spawn(process.execPath, ["--import", "tsx", "src/server-http.ts"], {
  cwd: new URL("..", import.meta.url),
  env: {
    ...process.env,
    PORT: port,
    BASE_URL: `http://localhost:${port}`,
    // Nothing listens there, so every sign-in is refused before a code is issued.
    BACKEND_URL: "http://127.0.0.1:9",
    APP_ENV: "development",
    JWT_SECRET: "redirect-test-secret-at-least-32-characters",
  },
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

  const registration = await fetch(`${base}/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_name: "redirect test", redirect_uris: ["http://localhost/callback"] }),
  });
  assert.equal(registration.status, 201);
  const { client_id } = await registration.json() as { client_id: string };

  const params = (redirect_uri: string) => ({
    response_type: "code", client_id, redirect_uri, code_challenge: "challenge", code_challenge_method: "S256",
  });
  const authorizeGet = (redirect_uri: string) =>
    fetch(`${base}/authorize?${new URLSearchParams(params(redirect_uri))}`, { redirect: "manual" });
  const authorizePost = (redirect_uri: string) => fetch(`${base}/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ ...params(redirect_uri), username: "nobody", password: "wrong", code: "000000" }),
    redirect: "manual",
  });

  const loginForm = await authorizeGet("http://localhost:45789/callback");
  assert.equal(loginForm.status, 200);
  assert.match(await loginForm.text(), /value="http:\/\/localhost:45789\/callback"/);
  // A refused sign-in re-renders the form, so the redirect URI passed the check.
  assert.equal((await authorizePost("http://localhost:45789/callback")).status, 401);

  for (const redirect_uri of ["http://localhost:45789/evil", "http://127.0.0.1:45789/callback", "https://evil.example/callback"]) {
    for (const response of [await authorizeGet(redirect_uri), await authorizePost(redirect_uri)]) {
      assert.equal(response.status, 400, redirect_uri);
      assert.deepEqual(await response.json(), { error: "invalid_redirect_uri" });
    }
  }
} finally {
  child.kill();
}

console.log(`OAuth redirect URIs: ${allowed.length} allowed and ${refused.length} refused cases, and both /authorize handlers ignore only the loopback port`);
