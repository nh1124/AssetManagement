// ============================================================
// OAuth 2.0 Authorization Server
// Authorization Code Flow with PKCE (RFC 6749 + RFC 7636)
// Dynamic Client Registration (RFC 7591)
// ============================================================

import crypto from "crypto";
import jwt from "jsonwebtoken";

// ─── Config ───────────────────────────────────────────────

export const JWT_SECRET = process.env.JWT_SECRET ?? "dev-secret-change-in-production";
export const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const ACCESS_TOKEN_TTL_SEC = 3600;
const REFRESH_TOKEN_TTL_SEC = 30 * 86400;
const AUTH_CODE_TTL_MS = 5 * 60 * 1000;

// ─── Types ────────────────────────────────────────────────

export interface RegisteredClient {
  client_id: string;
  client_name?: string;
  redirect_uris: string[];
  grant_types: string[];
  response_types: string[];
  token_endpoint_auth_method: string;
}

interface PendingAuthCode {
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: string;
  scope: string;
  state?: string;
  expires_at: number;
}

interface TokenPayload {
  sub: string;
  type: "access" | "refresh";
  client_id: string;
  scope: string;
  jti: string;
}

// ─── In-Memory Stores ─────────────────────────────────────

const clients = new Map<string, RegisteredClient>();
const pendingCodes = new Map<string, PendingAuthCode>();
const revokedJtis = new Set<string>();

setInterval(() => {
  const now = Date.now();
  for (const [code, entry] of pendingCodes) {
    if (entry.expires_at < now) pendingCodes.delete(code);
  }
}, 60_000);

// ─── Discovery ────────────────────────────────────────────

export function getDiscoveryMetadata() {
  return {
    issuer: BASE_URL,
    authorization_endpoint: `${BASE_URL}/authorize`,
    token_endpoint: `${BASE_URL}/token`,
    registration_endpoint: `${BASE_URL}/register`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
    scopes_supported: ["mcp"],
  };
}

// ─── Client Registration ──────────────────────────────────

export function registerClient(body: Record<string, unknown>): RegisteredClient {
  const client: RegisteredClient = {
    client_id: crypto.randomUUID(),
    client_name: body.client_name as string | undefined,
    redirect_uris: (body.redirect_uris as string[]) ?? [],
    grant_types: (body.grant_types as string[]) ?? ["authorization_code"],
    response_types: (body.response_types as string[]) ?? ["code"],
    token_endpoint_auth_method: (body.token_endpoint_auth_method as string) ?? "none",
  };
  clients.set(client.client_id, client);
  return client;
}

export function getClient(client_id: string): RegisteredClient | undefined {
  return clients.get(client_id);
}

// ─── Authorization Code ───────────────────────────────────

export function createAuthCode(params: {
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: string;
  scope?: string;
  state?: string;
}): string {
  const code = crypto.randomBytes(32).toString("base64url");
  pendingCodes.set(code, {
    client_id: params.client_id,
    redirect_uri: params.redirect_uri,
    code_challenge: params.code_challenge,
    code_challenge_method: params.code_challenge_method ?? "S256",
    scope: params.scope ?? "mcp",
    state: params.state,
    expires_at: Date.now() + AUTH_CODE_TTL_MS,
  });
  return code;
}

// ─── PKCE ─────────────────────────────────────────────────

function verifyPKCE(verifier: string, challenge: string, method: string): boolean {
  if (method === "S256") {
    return crypto.createHash("sha256").update(verifier).digest("base64url") === challenge;
  }
  return verifier === challenge;
}

// ─── Tokens ───────────────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
  scope: string;
}

export function exchangeCodeForTokens(params: {
  code: string;
  client_id: string;
  redirect_uri: string;
  code_verifier: string;
}): TokenResponse | null {
  const entry = pendingCodes.get(params.code);
  if (!entry) return null;
  if (entry.expires_at < Date.now()) { pendingCodes.delete(params.code); return null; }
  if (entry.client_id !== params.client_id) return null;
  if (entry.redirect_uri !== params.redirect_uri) return null;
  if (!verifyPKCE(params.code_verifier, entry.code_challenge, entry.code_challenge_method)) return null;

  pendingCodes.delete(params.code);
  return issueTokenPair(params.client_id, entry.scope);
}

export function refreshAccessToken(refresh_token: string): TokenResponse | null {
  try {
    const payload = jwt.verify(refresh_token, JWT_SECRET) as TokenPayload;
    if (payload.type !== "refresh") return null;
    if (revokedJtis.has(payload.jti)) return null;
    revokedJtis.add(payload.jti);
    return issueTokenPair(payload.client_id, payload.scope);
  } catch {
    return null;
  }
}

function issueTokenPair(client_id: string, scope: string): TokenResponse {
  const jti_access = crypto.randomUUID();
  const jti_refresh = crypto.randomUUID();

  const access_token = jwt.sign(
    { sub: "user", type: "access", client_id, scope, jti: jti_access } as TokenPayload,
    JWT_SECRET,
    { expiresIn: ACCESS_TOKEN_TTL_SEC }
  );
  const refresh_token = jwt.sign(
    { sub: "user", type: "refresh", client_id, scope, jti: jti_refresh } as TokenPayload,
    JWT_SECRET,
    { expiresIn: REFRESH_TOKEN_TTL_SEC }
  );

  return { access_token, refresh_token, token_type: "Bearer", expires_in: ACCESS_TOKEN_TTL_SEC, scope };
}

export function validateAccessToken(token: string): boolean {
  try {
    const payload = jwt.verify(token, JWT_SECRET) as TokenPayload;
    if (payload.type !== "access") return false;
    if (revokedJtis.has(payload.jti)) return false;
    return true;
  } catch {
    return false;
  }
}
