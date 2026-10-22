import assert from "node:assert/strict";
import crypto from "node:crypto";
import { createAuthCode, decodeAccessToken, exchangeCodeForTokens, refreshAccessToken } from "../src/auth.js";

const verifier = crypto.randomBytes(32).toString("base64url");
const resource = "http://localhost:13000/mcp";
const authTime = Date.now() - 60_123;
const code = createAuthCode({
  client_id: "review-client", redirect_uri: "http://localhost/callback",
  code_challenge: crypto.createHash("sha256").update(verifier).digest("base64url"),
  code_challenge_method: "S256", resource, allow_refresh_token: true,
  username: "tester", backend_client_id: 1, issuer: "http://localhost:13000",
  auth_time_ms: authTime,
});
let tokens = exchangeCodeForTokens({ code, client_id: "review-client", redirect_uri: "http://localhost/callback",
  code_verifier: verifier, resource, canonical_resource: resource });
assert(tokens);
assert.equal(decodeAccessToken(tokens.access_token)?.auth_time_ms, authTime);
// More than one rotation proves that every refresh grant retains the first time.
for (let rotation = 0; rotation < 3; rotation++) {
  assert(tokens.refresh_token);
  const oldRefresh = tokens.refresh_token;
  tokens = refreshAccessToken({ client_id: "review-client", refresh_token: oldRefresh, canonical_resource: resource });
  assert(tokens);
  assert.equal(decodeAccessToken(tokens.access_token)?.auth_time_ms, authTime);
  assert.equal(refreshAccessToken({ client_id: "review-client", refresh_token: oldRefresh, canonical_resource: resource }), null);
}
console.log("OAuth authorization time survives code exchange and three refresh rotations");
