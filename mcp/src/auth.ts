// ============================================================
// OAuth 2.0 Authorization Server
// Authorization Code Flow with PKCE (RFC 6749 + RFC 7636)
// Dynamic Client Registration (RFC 7591)
// Client ID Metadata Document (CIMD)
// Opaque Refresh Tokens with rotation (RFC 6749 §10.4)
// Resource Indicators (RFC 8707)
// ============================================================

import crypto from "crypto";
import jwt from "jsonwebtoken";

// ─── Config ───────────────────────────────────────────────

export const JWT_SECRET = process.env.JWT_SECRET ?? "dev-secret-change-in-production";
const ACCESS_TOKEN_TTL_SEC = 3600;
const REFRESH_TOKEN_TTL_MS = 30 * 86400 * 1000; // 30 days
const AUTH_CODE_TTL_MS = 5 * 60 * 1000;
const CLIENT_METADATA_CACHE_TTL_MS = 5 * 60 * 1000;
const CLIENT_METADATA_FETCH_TIMEOUT_MS = 5000;
const CLIENT_METADATA_MAX_BYTES = 64 * 1024;

// ─── Types ────────────────────────────────────────────────

type OAuthGrantType = "authorization_code" | "refresh_token";
type OAuthClientSource = "dynamic_client_registration" | "client_id_metadata_document";

export interface RegisteredClient {
  client_id: string;
  client_name?: string;
  redirect_uris: string[];
  grant_types: OAuthGrantType[];
  response_types: string[];
  token_endpoint_auth_method: "none";
  source: OAuthClientSource;
  created_at_ms: number;
}

interface PendingAuthCode {
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: string;
  scope: string;
  state?: string;
  resource: string;
  allow_refresh_token: boolean;
  username: string;
  expires_at: number;
}

interface OAuthRefreshTokenRecord {
  token_hash: string;
  client_id: string;
  scope: string;
  resource: string;
  username: string;
  issued_at_ms: number;
  expires_at_ms: number;
  revoked_at_ms?: number;
  replaced_by_hash?: string;
}

// ─── In-Memory Stores ─────────────────────────────────────

const registeredClients = new Map<string, RegisteredClient>();
const clientMetadataCache = new Map<string, { client: RegisteredClient; expires_at_ms: number }>();
const pendingCodes = new Map<string, PendingAuthCode>();
const refreshTokenStore = new Map<string, OAuthRefreshTokenRecord>();

// ─── Periodic Cleanup ─────────────────────────────────────

setInterval(() => {
  const now = Date.now();
  for (const [code, entry] of pendingCodes) {
    if (entry.expires_at < now) pendingCodes.delete(code);
  }
  for (const [hash, record] of refreshTokenStore) {
    if (record.expires_at_ms < now) refreshTokenStore.delete(hash);
  }
}, 60_000);

// ─── Utilities ────────────────────────────────────────────

function hashToken(value: string): string {
  return crypto.createHash("sha256").update(value, "utf8").digest("base64url");
}

function verifyPKCE(verifier: string, challenge: string, method: string): boolean {
  if (method === "S256") {
    return crypto.createHash("sha256").update(verifier).digest("base64url") === challenge;
  }
  return verifier === challenge;
}

function isHttpsUrl(s: string): boolean {
  try { return new URL(s).protocol === "https:"; } catch { return false; }
}

// ─── Discovery Metadata ───────────────────────────────────

export function getDiscoveryMetadata(issuer: string) {
  return {
    issuer,
    authorization_endpoint: `${issuer}/authorize`,
    token_endpoint: `${issuer}/token`,
    registration_endpoint: `${issuer}/register`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
    scopes_supported: ["mcp"],
    client_id_metadata_document_supported: true,
  };
}

// ─── Client ID Metadata Document (CIMD) ───────────────────

async function fetchClientMetadata(clientId: string): Promise<RegisteredClient> {
  const url = new URL(clientId);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), CLIENT_METADATA_FETCH_TIMEOUT_MS);

  let rawText: string;
  try {
    const response = await fetch(url.toString(), {
      method: "GET",
      headers: { Accept: "application/json" },
      redirect: "error",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`metadata fetch failed: HTTP ${response.status}`);

    const contentLength = Number(response.headers.get("content-length") ?? "0");
    if (contentLength > CLIENT_METADATA_MAX_BYTES) throw new Error("metadata response exceeds size limit");

    rawText = await response.text();
    if (rawText.length > CLIENT_METADATA_MAX_BYTES) throw new Error("metadata response exceeds size limit");
  } finally {
    clearTimeout(timeoutId);
  }

  const metadata = JSON.parse(rawText) as Record<string, unknown>;

  if (typeof metadata.client_id !== "string" || metadata.client_id !== clientId) {
    throw new Error("client_id mismatch in metadata document");
  }
  const redirectUris = Array.isArray(metadata.redirect_uris)
    ? (metadata.redirect_uris as unknown[]).filter((v): v is string => typeof v === "string").map(v => v.trim()).filter(Boolean)
    : [];
  if (redirectUris.length === 0) {
    throw new Error("redirect_uris required in metadata document");
  }

  return {
    client_id: clientId,
    client_name: typeof metadata.client_name === "string" ? metadata.client_name : undefined,
    redirect_uris: redirectUris,
    grant_types: ["authorization_code"],
    response_types: ["code"],
    token_endpoint_auth_method: "none",
    source: "client_id_metadata_document",
    created_at_ms: Date.now(),
  };
}

export async function resolveClient(clientId: string): Promise<RegisteredClient | undefined> {
  if (isHttpsUrl(clientId)) {
    const cached = clientMetadataCache.get(clientId);
    if (cached && cached.expires_at_ms > Date.now()) return cached.client;
    if (cached) clientMetadataCache.delete(clientId);
    try {
      const client = await fetchClientMetadata(clientId);
      clientMetadataCache.set(clientId, { client, expires_at_ms: Date.now() + CLIENT_METADATA_CACHE_TTL_MS });
      return client;
    } catch (err) {
      console.warn("[oauth] CIMD fetch failed", { client_id: clientId, error: (err as Error).message });
      return undefined;
    }
  }
  return registeredClients.get(clientId);
}

// ─── Dynamic Client Registration ──────────────────────────

export interface DcrResponse extends RegisteredClient {
  client_id_issued_at: number;
}

export function registerClient(body: Record<string, unknown>): DcrResponse {
  const rawGrantTypes = Array.isArray(body.grant_types)
    ? (body.grant_types as unknown[]).filter((g): g is string => typeof g === "string")
    : [];
  const grantTypes: OAuthGrantType[] = rawGrantTypes
    .filter((g): g is OAuthGrantType => g === "authorization_code" || g === "refresh_token");
  if (!grantTypes.includes("authorization_code")) grantTypes.unshift("authorization_code");

  const redirectUris = Array.isArray(body.redirect_uris)
    ? (body.redirect_uris as unknown[]).filter((v): v is string => typeof v === "string").map(v => v.trim()).filter(Boolean)
    : [];

  const now = Date.now();
  const client: RegisteredClient = {
    client_id: `mcp_${crypto.randomBytes(16).toString("hex")}`,
    client_name: typeof body.client_name === "string" ? body.client_name : undefined,
    redirect_uris: redirectUris,
    grant_types: grantTypes,
    response_types: ["code"],
    token_endpoint_auth_method: "none",
    source: "dynamic_client_registration",
    created_at_ms: now,
  };
  registeredClients.set(client.client_id, client);
  return { ...client, client_id_issued_at: Math.floor(now / 1000) };
}

// ─── Authorization Code ───────────────────────────────────

export function createAuthCode(params: {
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: string;
  scope?: string;
  state?: string;
  resource: string;
  allow_refresh_token: boolean;
  username: string;
}): string {
  const code = crypto.randomBytes(32).toString("base64url");
  pendingCodes.set(code, {
    client_id: params.client_id,
    redirect_uri: params.redirect_uri,
    code_challenge: params.code_challenge,
    code_challenge_method: params.code_challenge_method ?? "S256",
    scope: params.scope ?? "mcp",
    state: params.state,
    resource: params.resource,
    allow_refresh_token: params.allow_refresh_token,
    username: params.username,
    expires_at: Date.now() + AUTH_CODE_TTL_MS,
  });
  return code;
}

// ─── Token Issuance ───────────────────────────────────────

function issueAccessJwt(params: { client_id: string; scope: string; resource: string; username: string }): string {
  return jwt.sign(
    { sub: params.username, type: "access", client_id: params.client_id, scope: params.scope, username: params.username },
    JWT_SECRET,
    {
      expiresIn: ACCESS_TOKEN_TTL_SEC,
      ...(params.resource ? { audience: [params.resource] } : {}),
    }
  );
}

function issueOpaqueRefreshToken(params: { client_id: string; scope: string; resource: string; username: string }): string {
  const token = crypto.randomBytes(48).toString("base64url");
  const hash = hashToken(token);
  const now = Date.now();
  refreshTokenStore.set(hash, {
    token_hash: hash,
    client_id: params.client_id,
    scope: params.scope,
    resource: params.resource,
    username: params.username,
    issued_at_ms: now,
    expires_at_ms: now + REFRESH_TOKEN_TTL_MS,
  });
  return token;
}

// ─── Token Exchange ───────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  token_type: "Bearer";
  expires_in: number;
  scope: string;
}

export function exchangeCodeForTokens(params: {
  code: string;
  client_id: string;
  redirect_uri: string;
  code_verifier: string;
  resource: string | undefined;
  canonical_resource: string;
}): TokenResponse | null {
  const entry = pendingCodes.get(params.code);
  if (!entry) { console.warn("[oauth] code not found"); return null; }
  if (entry.expires_at < Date.now()) { pendingCodes.delete(params.code); console.warn("[oauth] code expired"); return null; }
  if (entry.client_id !== params.client_id) { pendingCodes.delete(params.code); console.warn("[oauth] client_id mismatch"); return null; }
  if (entry.redirect_uri !== params.redirect_uri) {
    pendingCodes.delete(params.code);
    console.warn("[oauth] redirect_uri mismatch", { stored: entry.redirect_uri, received: params.redirect_uri });
    return null;
  }

  // Use the resource negotiated at authorize time; only log a warning on mismatch.
  const effectiveResource = entry.resource;
  if (params.resource && params.resource !== effectiveResource) {
    console.warn("[oauth] resource mismatch (non-fatal)", { token_request: params.resource, stored: effectiveResource });
  }

  if (!verifyPKCE(params.code_verifier, entry.code_challenge, entry.code_challenge_method)) {
    pendingCodes.delete(params.code);
    console.warn("[oauth] PKCE verification failed");
    return null;
  }

  pendingCodes.delete(params.code);
  console.info("[oauth] code exchanged for tokens", { client_id: params.client_id, username: entry.username });

  const access_token = issueAccessJwt({
    client_id: params.client_id,
    scope: entry.scope,
    resource: effectiveResource,
    username: entry.username,
  });
  const refresh_token = entry.allow_refresh_token
    ? issueOpaqueRefreshToken({ client_id: params.client_id, scope: entry.scope, resource: effectiveResource, username: entry.username })
    : undefined;

  return { access_token, refresh_token, token_type: "Bearer", expires_in: ACCESS_TOKEN_TTL_SEC, scope: entry.scope };
}

export function refreshAccessToken(params: {
  client_id: string;
  refresh_token: string;
  canonical_resource: string;
}): TokenResponse | null {
  const hash = hashToken(params.refresh_token);
  const record = refreshTokenStore.get(hash);
  if (!record) { console.warn("[oauth] refresh token not found"); return null; }
  if (record.revoked_at_ms) { console.warn("[oauth] refresh token revoked"); return null; }
  if (record.expires_at_ms < Date.now()) { refreshTokenStore.delete(hash); console.warn("[oauth] refresh token expired"); return null; }
  if (record.client_id !== params.client_id) { console.warn("[oauth] refresh token client_id mismatch"); return null; }

  // Non-fatal resource check for refresh (resource may differ across tunnel restarts)
  if (record.resource !== params.canonical_resource) {
    console.warn("[oauth] refresh resource mismatch (non-fatal)", { stored: record.resource, canonical: params.canonical_resource });
  }

  // Rotate: mark old token as revoked
  record.revoked_at_ms = Date.now();

  const new_refresh_token = issueOpaqueRefreshToken({
    client_id: params.client_id,
    scope: record.scope,
    resource: record.resource,
    username: record.username,
  });
  record.replaced_by_hash = hashToken(new_refresh_token);

  const access_token = issueAccessJwt({
    client_id: params.client_id,
    scope: record.scope,
    resource: record.resource,
    username: record.username,
  });

  console.info("[oauth] refresh token rotated", { client_id: params.client_id, username: record.username });
  return {
    access_token,
    refresh_token: new_refresh_token,
    token_type: "Bearer",
    expires_in: ACCESS_TOKEN_TTL_SEC,
    scope: record.scope,
  };
}

// ─── Access Token Validation ──────────────────────────────

export function validateAccessToken(token: string): boolean {
  try {
    const payload = jwt.verify(token, JWT_SECRET) as { type?: string };
    return payload.type === "access";
  } catch {
    return false;
  }
}
