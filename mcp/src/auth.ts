// ============================================================
// OAuth 2.0 front door of the MCP server (WP35)
// Authorization Code Flow with PKCE (RFC 6749 + RFC 7636)
// Client ID Metadata Documents (CIMD), Dynamic Client Registration (RFC 7591)
// Resource Indicators (RFC 8707), issuer in the response (RFC 9207)
//
// This process keeps no OAuth state. DCR registrations, the connections people
// make, codes and refresh tokens live in the backend, which also signs the access
// tokens (owner 2026-10-24, C2): re-creating this container signs nobody out,
// and a person can end one connection from the app.
// ============================================================

import dns from "node:dns";
import https from "node:https";
import net from "node:net";
import jwt from "jsonwebtoken";

// ─── Config ───────────────────────────────────────────────

const DEFAULT_JWT_SECRETS = new Set([
  "dev-secret-change-in-production",
  "change-me-to-a-secret-key-at-least-32-chars",
]);

function requireJwtSecret(): string {
  const secret = process.env.JWT_SECRET ?? "dev-secret-change-in-production";
  const appEnv = (process.env.APP_ENV ?? "development").trim().toLowerCase();
  if (appEnv === "production" && DEFAULT_JWT_SECRETS.has(secret)) {
    throw new Error("Invalid production configuration: JWT_SECRET must be changed in production");
  }
  return secret;
}

export const JWT_SECRET = requireJwtSecret();
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://backend:8000").replace(/\/$/, "");
const BACKEND_TIMEOUT_MS = 10_000;
const CLIENT_METADATA_DEFAULT_CACHE_MS = 5 * 60 * 1000;
const CLIENT_METADATA_MIN_CACHE_MS = 60 * 1000;
const CLIENT_METADATA_MAX_CACHE_MS = 24 * 60 * 60 * 1000;
const CLIENT_METADATA_MAX_CACHED = 200;
const CLIENT_METADATA_FETCH_TIMEOUT_MS = 5000;
// The CIMD draft (§8.7) recommends reading no more than 5 KB of a document.
const CLIENT_METADATA_MAX_BYTES = 5 * 1024;

// ─── Types ────────────────────────────────────────────────

type OAuthGrantType = "authorization_code" | "refresh_token";
export type OAuthClientSource = "dcr" | "cimd";

/** What /authorize needs to know about an app: its name, where it may be sent back, what it may ask for. */
export interface OAuthClient {
  client_id: string;
  client_name?: string;
  redirect_uris: string[];
  grant_types: OAuthGrantType[];
  source: OAuthClientSource;
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
    authorization_response_iss_parameter_supported: true,
  };
}

// ─── Redirect URIs ────────────────────────────────────────

const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** MCP authorization: every redirect URI is https or a loopback http URL. */
export function isAllowedRedirectUri(uri: string): boolean {
  let parsed: URL;
  try { parsed = new URL(uri); } catch { return false; }
  if (parsed.username || parsed.password || parsed.hash) return false;
  return parsed.protocol === "https:" || (parsed.protocol === "http:" && LOOPBACK_HOSTNAMES.has(parsed.hostname));
}

export function isLoopbackRedirectUri(uri: string): boolean {
  try {
    const parsed = new URL(uri);
    return parsed.protocol === "http:" && LOOPBACK_HOSTNAMES.has(parsed.hostname);
  } catch { return false; }
}

// Native apps listen on a random loopback port, so RFC 8252 §7.3 says the
// port of a loopback http redirect URI is ignored when matching (Claude Code
// registers "http://localhost/callback" and calls back on any port). Only the
// port is ignored: scheme, host, path and query must match the registered URI
// character for character, and every other redirect URI is an exact match.
const LOOPBACK_REDIRECT = /^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?([/?][^#]*)?$/;

function loopbackRedirectWithoutPort(uri: string): string | null {
  const match = LOOPBACK_REDIRECT.exec(uri);
  if (!match) return null;
  const [, host, port, rest = ""] = match;
  if (port !== undefined && (port.startsWith("0") || Number(port) > 65535)) return null;
  // Re-parse so that nothing the regex let through can point elsewhere.
  let parsed: URL;
  try { parsed = new URL(uri); } catch { return null; }
  if (parsed.protocol !== "http:" || !LOOPBACK_HOSTNAMES.has(parsed.hostname)) return null;
  if (parsed.username || parsed.password || parsed.hash) return null;
  return `http://${host}${rest}`;
}

export function isRegisteredRedirectUri(registered: readonly string[], requested: string): boolean {
  if (registered.includes(requested)) return true;
  const requestedWithoutPort = loopbackRedirectWithoutPort(requested);
  if (requestedWithoutPort === null) return false;
  return registered.some(uri => loopbackRedirectWithoutPort(uri) === requestedWithoutPort);
}

// ─── Client ID Metadata Document (CIMD) ───────────────────

// The CIMD draft (§8.6): never fetch a document from a special-use address, so a
// client_id cannot make this server probe the compose network or the host.
// Two lists: a BlockList holding the IPv4-mapped IPv6 range would match every
// IPv4 address checked against it.
const SPECIAL_USE_V4 = new net.BlockList();
for (const [prefix, bits] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8], ["169.254.0.0", 16],
  ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24], ["192.88.99.0", 24], ["192.168.0.0", 16],
  ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 4], ["240.0.0.0", 4],
] as const) SPECIAL_USE_V4.addSubnet(prefix, bits, "ipv4");
const SPECIAL_USE_V6 = new net.BlockList();
for (const [prefix, bits] of [
  ["::", 128], ["::1", 128], ["::ffff:0:0", 96], ["64:ff9b::", 96], ["64:ff9b:1::", 48], ["100::", 64],
  ["2001::", 23], ["2001:db8::", 32], ["2002::", 16], ["fc00::", 7], ["fe80::", 10], ["ff00::", 8],
] as const) SPECIAL_USE_V6.addSubnet(prefix, bits, "ipv6");

export function isSpecialUseAddress(address: string): boolean {
  const family = net.isIP(address);
  if (family === 0) return true;
  return family === 6 ? SPECIAL_USE_V6.check(address, "ipv6") : SPECIAL_USE_V4.check(address, "ipv4");
}

type LookupCallback = (error: NodeJS.ErrnoException | null, address: string | dns.LookupAddress[], family?: number) => void;

// Checked at connect time, after resolution, so a name cannot pass the check and
// then resolve to a private address (DNS rebinding). Only public addresses are
// dialled; a name with none fails.
function publicOnlyLookup(hostname: string, options: dns.LookupOptions, callback: LookupCallback): void {
  dns.lookup(hostname, { ...options, all: true }, (error, addresses) => {
    if (error) { callback(error, ""); return; }
    const list = (addresses as dns.LookupAddress[]).filter(entry => !isSpecialUseAddress(entry.address));
    if (list.length === 0) {
      callback(Object.assign(new Error(`client metadata host is not public: ${hostname}`), { code: "ENOTPUBLIC" }), "");
      return;
    }
    if (options.all) callback(null, list);
    else callback(null, list[0].address, list[0].family);
  });
}

interface FetchedDocument { body: string; cacheControl: string | undefined }

function fetchPublicJson(url: URL): Promise<FetchedDocument> {
  const literal = url.hostname.replace(/^\[|\]$/g, "");
  if (net.isIP(literal) && isSpecialUseAddress(literal)) {
    return Promise.reject(new Error(`client metadata host is not public: ${url.hostname}`));
  }
  return new Promise((resolve, reject) => {
    const request = https.request(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      lookup: publicOnlyLookup as unknown as typeof dns.lookup,
      timeout: CLIENT_METADATA_FETCH_TIMEOUT_MS,
    }, response => {
      // Redirects are not followed (CIMD §5): anything but 200 is a failure.
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`metadata fetch failed: HTTP ${response.statusCode}`));
        return;
      }
      const chunks: Buffer[] = [];
      let size = 0;
      response.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > CLIENT_METADATA_MAX_BYTES) { request.destroy(new Error("metadata response exceeds size limit")); return; }
        chunks.push(chunk);
      });
      response.on("end", () => resolve({ body: Buffer.concat(chunks).toString("utf8"), cacheControl: response.headers["cache-control"] }));
      response.on("error", reject);
    });
    request.on("timeout", () => request.destroy(new Error("metadata fetch timed out")));
    request.on("error", reject);
    request.end();
  });
}

/** How long a fetched document may be reused: its Cache-Control, within bounds; none for no-store. */
export function metadataCacheMs(cacheControl: string | undefined): number {
  const directives = (cacheControl ?? "").toLowerCase().split(",").map(part => part.trim());
  if (directives.some(directive => directive === "no-store" || directive === "no-cache")) return 0;
  const maxAge = directives.map(directive => /^max-age=(\d+)$/.exec(directive)).find(Boolean);
  if (!maxAge) return CLIENT_METADATA_DEFAULT_CACHE_MS;
  return Math.min(Math.max(Number(maxAge[1]) * 1000, CLIENT_METADATA_MIN_CACHE_MS), CLIENT_METADATA_MAX_CACHE_MS);
}

/** A client_id that names a metadata document: an https URL with a path (CIMD §3). */
export function isMetadataDocumentClientId(clientId: string): boolean {
  try {
    const url = new URL(clientId);
    return url.protocol === "https:" && url.pathname !== "/" && !url.hash && !url.username && !url.password;
  } catch { return false; }
}

/** The app a metadata document describes, or an error naming what is wrong with it. */
export function clientFromMetadata(clientId: string, metadata: Record<string, unknown>): OAuthClient {
  if (typeof metadata.client_id !== "string" || metadata.client_id !== clientId) {
    throw new Error("client_id mismatch in metadata document");
  }
  const redirectUris = Array.isArray(metadata.redirect_uris)
    ? (metadata.redirect_uris as unknown[]).filter((v): v is string => typeof v === "string").map(v => v.trim())
      .filter(isAllowedRedirectUri)
    : [];
  if (redirectUris.length === 0) throw new Error("redirect_uris required in metadata document");
  // The app says whether it wants refresh tokens; Claude Code does (owner 2026-10-24, C5).
  const declared = Array.isArray(metadata.grant_types) ? metadata.grant_types as unknown[] : [];
  const grantTypes: OAuthGrantType[] = ["authorization_code"];
  if (declared.includes("refresh_token")) grantTypes.push("refresh_token");
  return {
    client_id: clientId,
    client_name: typeof metadata.client_name === "string" ? metadata.client_name.slice(0, 200) : undefined,
    redirect_uris: redirectUris,
    grant_types: grantTypes,
    source: "cimd",
  };
}

const clientMetadataCache = new Map<string, { client: OAuthClient; expires_at_ms: number }>();

async function resolveMetadataDocument(clientId: string): Promise<OAuthClient | undefined> {
  const cached = clientMetadataCache.get(clientId);
  if (cached && cached.expires_at_ms > Date.now()) return cached.client;
  clientMetadataCache.delete(clientId);
  try {
    const { body, cacheControl } = await fetchPublicJson(new URL(clientId));
    const client = clientFromMetadata(clientId, JSON.parse(body) as Record<string, unknown>);
    const cacheMs = metadataCacheMs(cacheControl);
    if (cacheMs > 0) {
      if (clientMetadataCache.size >= CLIENT_METADATA_MAX_CACHED) {
        const oldest = clientMetadataCache.keys().next().value;
        if (oldest !== undefined) clientMetadataCache.delete(oldest);
      }
      clientMetadataCache.set(clientId, { client, expires_at_ms: Date.now() + cacheMs });
    }
    return client;
  } catch (err) {
    // Errors are never cached (CIMD §9.1).
    console.warn("[oauth] CIMD fetch failed", { client_id: clientId, error: (err as Error).message });
    return undefined;
  }
}

// ─── The backend's half ───────────────────────────────────

export interface BackendReply { status: number; body: Record<string, unknown> }

/** POST or GET one of the backend's /auth/mcp endpoints; a network failure answers 502. */
export async function callBackend(path: string, body?: unknown): Promise<BackendReply> {
  try {
    const res = await fetch(`${BACKEND_URL}/auth/mcp${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const text = await res.text();
    let parsed: unknown = {};
    try { parsed = text ? JSON.parse(text) : {}; } catch { parsed = {}; }
    return { status: res.status, body: parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {} };
  } catch (err) {
    console.warn("[oauth] backend unreachable", { path, error: (err as Error).message });
    return { status: 502, body: { error: "temporarily_unavailable" } };
  }
}

export async function resolveClient(clientId: string): Promise<OAuthClient | undefined> {
  if (isMetadataDocumentClientId(clientId)) return resolveMetadataDocument(clientId);
  if (!/^mcp_[0-9a-f]{32}$/.test(clientId)) return undefined;
  const reply = await callBackend(`/clients/${encodeURIComponent(clientId)}`);
  if (reply.status !== 200) return undefined;
  const grantTypes = Array.isArray(reply.body.grant_types) ? reply.body.grant_types as OAuthGrantType[] : ["authorization_code" as const];
  return {
    client_id: clientId,
    client_name: typeof reply.body.client_name === "string" ? reply.body.client_name : undefined,
    redirect_uris: Array.isArray(reply.body.redirect_uris) ? reply.body.redirect_uris as string[] : [],
    grant_types: grantTypes,
    source: "dcr",
  };
}

// ─── Resource and Token Audience (RFC 8707) ───────────────

// A token names the MCP server it was issued for in its audience. This server
// issues tokens only for its own address and accepts only tokens for its own
// address plus those listed in MCP_ACCEPTED_RESOURCES (other MCP servers that
// share MCP_JWT_SECRET). Removing an address from the list and restarting
// closes it again. "Own address" is the MCP endpoint with and without /mcp,
// because the server answers on both.

/** Resources are compared as URL parses them, without a trailing slash; anything else is not a resource. */
export function normalizeResource(value: string): string | null {
  let url: URL;
  try { url = new URL(value.trim()); } catch { return null; }
  if ((url.protocol !== "https:" && url.protocol !== "http:") || url.username || url.password || url.hash) return null;
  return `${url.protocol}//${url.host}${url.pathname.replace(/\/+$/, "")}${url.search}`;
}

function configuredResources(): string[] {
  const entries = (process.env.MCP_ACCEPTED_RESOURCES ?? "").split(",").map(value => value.trim()).filter(Boolean);
  return entries.map(value => {
    const normalized = normalizeResource(value);
    // Refuse to start rather than silently drop a mistyped address.
    if (normalized === null) throw new Error(`Invalid configuration: MCP_ACCEPTED_RESOURCES entry is not an http(s) URL: ${value}`);
    return normalized;
  });
}

export const EXTRA_ACCEPTED_RESOURCES = configuredResources();

export function ownResources(canonicalResource: string): string[] {
  const own = normalizeResource(canonicalResource);
  return own ? [...new Set([own, own.replace(/\/mcp$/, "")])] : [];
}

export function acceptedResources(canonicalResource: string, extra: readonly string[] = EXTRA_ACCEPTED_RESOURCES): string[] {
  return [...new Set([...ownResources(canonicalResource), ...extra])];
}

export function isResourceIn(resource: string, resources: readonly string[]): boolean {
  const normalized = normalizeResource(resource);
  return normalized !== null && resources.includes(normalized);
}

export function tokenAudienceAccepted(aud: string | string[] | undefined, accepted: readonly string[]): boolean {
  const audiences = Array.isArray(aud) ? aud : aud ? [aud] : [];
  return audiences.some(value => isResourceIn(value, accepted));
}

// ─── Access Token Validation ──────────────────────────────

export interface McpAccessTokenPayload {
  sub: string;
  type: "access";
  client_id: string;
  scope: string;
  username: string;
  backend_client_id: number;
  auth_time_ms: number;
  // The connection the token belongs to; the backend refuses it once that ends.
  cid: number;
  aud?: string | string[];
  iss?: string;
  exp?: number;
  iat?: number;
}

export function decodeAccessToken(token: string): McpAccessTokenPayload | null {
  try {
    const payload = jwt.verify(token, JWT_SECRET) as McpAccessTokenPayload;
    return payload.type === "access" ? payload : null;
  } catch (err) {
    console.warn("[oauth] token validation failed", { reason: (err as Error).message });
    return null;
  }
}

export function validateAccessToken(token: string): boolean {
  return decodeAccessToken(token) !== null;
}
