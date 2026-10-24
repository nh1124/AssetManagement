// ============================================================
// Asset Management MCP Server - HTTP (OAuth 2.0)
// ============================================================

import { randomUUID } from "node:crypto";
import express, { type Request, type Response, type NextFunction } from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { buildMcpServer } from "./server.js";
import {
  decodeAccessToken,
  getDiscoveryMetadata,
  callBackend,
  resolveClient,
  isRegisteredRedirectUri,
  isLoopbackRedirectUri,
  acceptedResources,
  ownResources,
  isResourceIn,
  tokenAudienceAccepted,
  EXTRA_ACCEPTED_RESOURCES,
} from "./auth.js";
import { withMcpRequestContext, type McpRequestContext } from "./api-client.js";

const PORT = parseInt(process.env.PORT ?? "3000");
const LOG_BODIES = process.env.MCP_LOG_BODIES === "1";
// Open registration (RFC 7591 §3) with a limit, so a loop cannot fill the backend's table.
const REGISTRATIONS_PER_MINUTE = 20;

// One JSON object per line, in the shape the backend logs use, so the two
// streams can be read together by correlation_id.
function logEvent(event: string, fields: Record<string, unknown>, level: "info" | "error" = "info"): void {
  const line = JSON.stringify({ ts: new Date().toISOString(), level, component: "mcp", event, ...fields });
  if (level === "error") console.error(line); else console.info(line);
}

// What the sign-in page says for each refusal the backend gives (/auth/mcp/authorize).
const SIGN_IN_REFUSALS: Record<string, { status: number; message: string }> = {
  invalid: { status: 401, message: "ユーザー名、パスワードまたは認証コードが正しくありません" },
  locked: { status: 429, message: "試行が多すぎます。しばらくしてからもう一度お試しください。" },
  setup_required: { status: 403, message: "先にアプリでサインインして、パスワードと認証アプリを設定してください。" },
  approval_pending: { status: 403, message: "このアカウントは管理者の承認待ちです。" },
};

const registrationTimes: number[] = [];

function registrationAllowed(now = Date.now()): boolean {
  while (registrationTimes.length && registrationTimes[0] <= now - 60_000) registrationTimes.shift();
  if (registrationTimes.length >= REGISTRATIONS_PER_MINUTE) return false;
  registrationTimes.push(now);
  return true;
}

// ─── Issuer / Resource helpers ────────────────────────────

function buildOAuthIssuer(req: Request): string {
  const configured = process.env.BASE_URL?.trim().replace(/\/$/, "");
  if (configured) return configured;

  const proto = req.headers["x-forwarded-proto"]?.toString().split(",")[0]?.trim();
  const host = (req.headers["x-forwarded-host"] ?? req.headers.host)?.toString().split(",")[0]?.trim();
  if (proto === "https" && host) return `https://${host}`;
  if (host) return `https://${host}`;
  return configured ?? `http://localhost:${PORT}`;
}

function buildCanonicalMcpResource(req: Request): string {
  return `${buildOAuthIssuer(req)}/mcp`;
}

// ─── App setup ────────────────────────────────────────────

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Request logger
app.use((req: Request, _res: Response, next: NextFunction) => {
  console.info(`[http] ${req.method} ${req.path}`, {
    user_agent: req.headers["user-agent"]?.slice(0, 60) ?? "(none)",
    has_auth: !!req.headers.authorization,
  });
  next();
});

// CORS
app.use((_req: Request, res: Response, next: NextFunction) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Mcp-Session-Id, Last-Event-ID, Mcp-Protocol-Version");
  next();
});
app.use((req: Request, res: Response, next: NextFunction) => {
  if (req.method === "OPTIONS") { res.sendStatus(204); return; }
  next();
});

// ─── OAuth Discovery ──────────────────────────────────────

// RFC 9728 — OAuth 2.0 Protected Resource Metadata
// Claude's MCP client checks this first to find the authorization server.
app.get("/.well-known/oauth-protected-resource", (req, res) => {
  const issuer = buildOAuthIssuer(req);
  res.json({
    resource: buildCanonicalMcpResource(req),
    authorization_servers: [issuer],
    scopes_supported: ["mcp"],
    bearer_methods_supported: ["header"],
  });
});

app.get("/.well-known/oauth-authorization-server", (req, res) => {
  const issuer = buildOAuthIssuer(req);
  console.info("[oauth] discovery requested", { issuer, user_agent: req.headers["user-agent"] ?? "(missing)" });
  res.json(getDiscoveryMetadata(issuer));
});

// ─── Dynamic Client Registration ──────────────────────────

// Kept for apps without a client ID metadata document (owner 2026-10-24, C1). The
// registration is stored by the backend, so it survives this container.
app.post("/register", async (req, res) => {
  if (!registrationAllowed()) { res.status(429).json({ error: "temporarily_unavailable" }); return; }
  const body = (req.body ?? {}) as Record<string, unknown>;
  const reply = await callBackend("/clients", {
    client_name: typeof body.client_name === "string" ? body.client_name : undefined,
    redirect_uris: Array.isArray(body.redirect_uris) ? body.redirect_uris.filter(v => typeof v === "string") : [],
    grant_types: Array.isArray(body.grant_types) ? body.grant_types.filter(v => typeof v === "string") : [],
  });
  if (reply.status === 201) {
    console.info("[oauth] client registered", {
      client_id: reply.body.client_id,
      client_name: reply.body.client_name,
      grant_types: reply.body.grant_types,
    });
  }
  res.status(reply.status === 422 ? 400 : reply.status).json(reply.status === 422 ? { error: "invalid_client_metadata" } : reply.body);
});

// ─── Authorization Endpoint ───────────────────────────────

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/'/g, "&#39;");
}

function renderLoginForm(params: {
  client_id: string;
  client_name?: string;
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: string;
  state?: string;
  scope: string;
  resource: string;
  response_type: string;
}, errorMsg?: string): string {
  const esc = escapeHtml;
  const errorHtml = errorMsg
    ? `<p style="color:#b91c1c;background:#fee2e2;padding:8px 12px;border-radius:8px;font-size:.85rem">${esc(errorMsg)}</p>`
    : "";
  // MCP authorization: the consent page names where the code goes, and warns when
  // that is this computer, since any local program can listen there.
  let redirectHost = params.redirect_uri;
  try { redirectHost = new URL(params.redirect_uri).host; } catch { /* shown as given */ }
  const loopbackHtml = isLoopbackRedirectUri(params.redirect_uri)
    ? `<p class="warn">このコンピューターで動いているアプリに許可します。自分で起動したアプリ（Claude Code など）の接続でなければ、ログインしないでください。</p>`
    : "";
  return `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Asset Management MCP - ログイン</title>
  <style>
    *,*::before,*::after{box-sizing:border-box}
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f0f2f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem}
    .card{background:#fff;padding:2rem;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);width:100%;max-width:360px}
    .logo{font-size:2rem;text-align:center;margin-bottom:.5rem}
    h1{font-size:1.1rem;color:#111;text-align:center;margin:0 0 .25rem}
    .app-label{font-size:.8rem;color:#666;text-align:center;margin-bottom:1.25rem}
    label{display:block;font-size:.85rem;font-weight:600;color:#333;margin-bottom:.4rem}
    input[type=text],input[type=password]{width:100%;padding:.75rem 1rem;border:1.5px solid #ddd;border-radius:10px;font-size:1rem;outline:none;margin-bottom:.75rem}
    input[type=text]:focus,input[type=password]:focus{border-color:#0070f3}
    button{width:100%;padding:.8rem;background:#0070f3;color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;margin-top:.25rem}
    button:hover{background:#005ed3}
    .note{font-size:.75rem;color:#888;text-align:center;margin-top:1rem}
    .warn{font-size:.8rem;color:#92400e;background:#fef3c7;padding:8px 12px;border-radius:8px}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">📊</div>
    <h1>Asset Management MCP</h1>
    <div class="app-label">接続アプリ: <strong>${esc(params.client_name ?? params.client_id)}</strong><br>戻り先: <strong>${esc(redirectHost)}</strong></div>
    ${loopbackHtml}
    ${errorHtml}
    <form method="POST" action="/authorize">
      <input type="hidden" name="response_type"          value="${esc(params.response_type)}">
      <input type="hidden" name="client_id"              value="${esc(params.client_id)}">
      <input type="hidden" name="redirect_uri"           value="${esc(params.redirect_uri)}">
      <input type="hidden" name="code_challenge"         value="${esc(params.code_challenge)}">
      <input type="hidden" name="code_challenge_method"  value="${esc(params.code_challenge_method)}">
      <input type="hidden" name="state"                  value="${esc(params.state ?? "")}">
      <input type="hidden" name="scope"                  value="${esc(params.scope)}">
      <input type="hidden" name="resource"               value="${esc(params.resource)}">
      <label for="un">ユーザー名</label>
      <input type="text" id="un" name="username" placeholder="username" autofocus required autocomplete="username">
      <label for="pw">パスワード</label>
      <input type="password" id="pw" name="password" placeholder="••••••••" required autocomplete="current-password">
      <label for="mfa-code">認証コード（6 桁、または回復コード）</label>
      <input type="text" id="mfa-code" name="code" required autocomplete="one-time-code" inputmode="numeric">
      <button type="submit">ログイン &amp; 許可</button>
    </form>
    <p class="note">スコープ: ${esc(params.scope)}<br>接続はアプリの 自動化 › AI でいつでも切断できます。</p>
  </div>
</body>
</html>`;
}

app.get("/authorize", async (req, res) => {
  const q = req.query as Record<string, string>;
  const { response_type, client_id, redirect_uri, code_challenge, code_challenge_method, state, scope } = q;
  const canonicalResource = buildCanonicalMcpResource(req);
  const resource = q.resource || canonicalResource;

  if (response_type !== "code") { res.status(400).json({ error: "unsupported_response_type" }); return; }
  if (!client_id || !redirect_uri || !code_challenge) { res.status(400).json({ error: "invalid_request" }); return; }

  const client = await resolveClient(client_id);
  if (!client) { res.status(400).json({ error: "invalid_client" }); return; }
  if (!isRegisteredRedirectUri(client.redirect_uris, redirect_uri)) { res.status(400).json({ error: "invalid_redirect_uri" }); return; }
  if (!isResourceIn(resource, ownResources(canonicalResource))) { res.status(400).json({ error: "invalid_target" }); return; }

  console.info("[oauth] authorize GET", { client_id, resource });

  res.setHeader("Content-Type", "text/html; charset=utf-8").send(renderLoginForm({
    client_id,
    client_name: client.client_name,
    redirect_uri,
    code_challenge,
    code_challenge_method: code_challenge_method ?? "S256",
    state,
    scope: scope ?? "mcp",
    resource,
    response_type,
  }));
});

app.post("/authorize", async (req, res) => {
  const b = req.body as Record<string, string>;
  const { response_type, client_id, redirect_uri, code_challenge, code_challenge_method, state, scope, username, password, code: factorCode } = b;
  const canonicalResource = buildCanonicalMcpResource(req);
  const resource = b.resource || canonicalResource;

  if (response_type !== "code") { res.status(400).json({ error: "unsupported_response_type" }); return; }
  if (!client_id || !redirect_uri || !code_challenge) { res.status(400).json({ error: "invalid_request" }); return; }

  const client = await resolveClient(client_id);
  if (!client) { res.status(400).json({ error: "invalid_client" }); return; }
  if (!isRegisteredRedirectUri(client.redirect_uris, redirect_uri)) { res.status(400).json({ error: "invalid_redirect_uri" }); return; }
  if (!isResourceIn(resource, ownResources(canonicalResource))) { res.status(400).json({ error: "invalid_target" }); return; }

  // The backend signs the person in (password + second factor) and records the
  // connection; the code it returns is the connection's.
  const issuer = buildOAuthIssuer(req);
  const reply = await callBackend("/authorize", {
    username: username ?? "",
    password: password ?? "",
    factor: factorCode ?? "",
    oauth_client_id: client_id,
    client_name: client.client_name,
    client_source: client.source,
    redirect_uri,
    code_challenge,
    code_challenge_method: code_challenge_method ?? "S256",
    scope: scope ?? "mcp",
    resource,
    issuer,
    allow_refresh: client.grant_types.includes("refresh_token"),
  });
  const code = reply.status === 200 && typeof reply.body.code === "string" ? reply.body.code : null;
  if (code === null) {
    const refusal = SIGN_IN_REFUSALS[String(reply.body.error)];
    if (!refusal) {
      console.warn("[oauth] authorize refused by the backend", { client_id, status: reply.status, error: reply.body.error });
      res.status(reply.status >= 500 ? 502 : 400).json({ error: reply.body.error ?? "server_error" });
      return;
    }
    res.status(refusal.status).setHeader("Content-Type", "text/html; charset=utf-8").send(renderLoginForm({
      client_id,
      client_name: client.client_name,
      redirect_uri,
      code_challenge,
      code_challenge_method: code_challenge_method ?? "S256",
      state,
      scope: scope ?? "mcp",
      resource,
      response_type,
    }, refusal.message));
    return;
  }

  console.info("[oauth] authorize POST success", { client_id, username: reply.body.username, resource });
  const redirectUrl = new URL(redirect_uri);
  redirectUrl.searchParams.set("code", code);
  if (state) redirectUrl.searchParams.set("state", state);
  // RFC 9207: the client checks the code came from the server it asked.
  redirectUrl.searchParams.set("iss", issuer);
  res.redirect(302, redirectUrl.toString());
});

// ─── Token Endpoint ───────────────────────────────────────

app.post("/token", async (req, res) => {
  const b = (req.body ?? {}) as Record<string, string>;
  const { grant_type, client_id } = b;
  // RFC 6749 §5.1: token responses are never cached.
  res.setHeader("Cache-Control", "no-store").setHeader("Pragma", "no-cache");

  console.info("[oauth] token request", {
    grant_type: grant_type || "(missing)",
    client_id: client_id || "(missing)",
    has_code: !!b.code,
    has_refresh_token: !!b.refresh_token,
    resource: b.resource || "(missing)",
  });

  if (grant_type !== "authorization_code" && grant_type !== "refresh_token") {
    res.status(400).json({ error: grant_type ? "unsupported_grant_type" : "invalid_request" }); return;
  }
  if (!client_id) { res.status(400).json({ error: "invalid_request" }); return; }

  // The backend redeems the code or rotates the refresh token and signs the access
  // token; the resource was fixed at /authorize and travels with the connection.
  const reply = await callBackend("/token", {
    grant_type,
    client_id,
    code: b.code,
    redirect_uri: b.redirect_uri,
    code_verifier: b.code_verifier,
    refresh_token: b.refresh_token,
  });
  if (reply.status === 200) {
    console.info("[oauth] access token issued", { grant_type, client_id, has_refresh: "refresh_token" in reply.body });
  } else {
    console.warn("[oauth] token request refused", { grant_type, client_id, status: reply.status, error: reply.body.error });
  }
  res.status(reply.status === 422 ? 400 : reply.status).json(reply.status === 422 ? { error: "invalid_request" } : reply.body);
});

// ─── Auth Middleware ───────────────────────────────────────

function requireBearer(req: Request, res: Response, next: NextFunction): void {
  const issuer = buildOAuthIssuer(req);
  const auth = req.headers.authorization;
  if (!auth?.startsWith("Bearer ")) {
    console.warn("[mcp] missing Bearer token", { method: req.method, path: req.path });
    res.setHeader("WWW-Authenticate",
      `Bearer realm="${issuer}", resource_metadata="${issuer}/.well-known/oauth-protected-resource", scope="mcp"`)
      .status(401).json({ error: "unauthorized" });
    return;
  }
  const token = auth.slice(7);
  const payload = decodeAccessToken(token);
  if (!payload) {
    console.warn("[mcp] invalid Bearer token", { method: req.method, path: req.path, token_prefix: auth.slice(7, 20) });
    res.setHeader("WWW-Authenticate", `Bearer realm="${issuer}", error="invalid_token"`).status(401).json({ error: "invalid_token" });
    return;
  }
  // A genuine token issued for another MCP server is refused unless that server is listed.
  if (!tokenAudienceAccepted(payload.aud, acceptedResources(buildCanonicalMcpResource(req)))) {
    console.warn("[mcp] Bearer token for another resource", { method: req.method, path: req.path, aud: payload.aud });
    res.setHeader("WWW-Authenticate", `Bearer realm="${issuer}", error="invalid_token", error_description="token not issued for this MCP server"`)
      .status(401).json({ error: "invalid_token" });
    return;
  }
  (req as Request & { mcpAuth?: McpRequestContext }).mcpAuth = {
    mcpAccessToken: token,
    mcpClientId: payload.client_id,
    username: payload.username,
    backendClientId: payload.backend_client_id,
  };
  next();
}

// ─── MCP Endpoint ─────────────────────────────────────────

// Shared Accept-header normalizer: MCP SDK requires both application/json and
// text/event-stream. ChatGPT's client omits text/event-stream, causing 406.
function normalizeMcpAccept(req: Request, _res: Response, next: NextFunction): void {
  if (req.method === "POST") {
    const accept = req.headers.accept ?? "";
    if (!accept.includes("text/event-stream")) {
      req.headers.accept = accept ? `${accept}, text/event-stream` : "application/json, text/event-stream";
    }
    console.info("[mcp] POST", {
      path: req.path,
      accept: req.headers.accept,
      has_auth: !!req.headers.authorization,
      ua: req.headers["user-agent"]?.slice(0, 40),
    });
  }
  next();
}

function toBuffer(chunk: unknown): Buffer | null {
  if (Buffer.isBuffer(chunk)) return chunk;
  if (chunk instanceof Uint8Array) return Buffer.from(chunk);
  if (typeof chunk === "string") return Buffer.from(chunk, "utf8");
  return null;
}

async function handleMcpPost(req: Request, res: Response): Promise<void> {
  const body = req.body as Record<string, unknown>;
  const method = Array.isArray(body) ? "(batch)" : (body?.method as string | undefined) ?? "(unknown)";
  const params = !Array.isArray(body) && body?.params && typeof body.params === "object"
    ? body.params as Record<string, unknown>
    : {};
  const toolName = method === "tools/call" && typeof params.name === "string" ? params.name : undefined;
  const authContext = (req as Request & { mcpAuth?: McpRequestContext }).mcpAuth;
  // Sent to the backend as X-Request-ID with every call this request makes,
  // so a tool call and the rows it wrote share one correlation_id.
  const requestId = `mcp-${randomUUID()}`;
  const startedAt = Date.now();
  const who = { correlation_id: requestId, method, tool: toolName, mcp_client_id: authContext?.mcpClientId, username: authContext?.username };
  logEvent("mcp.request.start", who);

  // Count the bytes written to the response. The bytes themselves are the
  // user's financial data and are kept out of the log unless MCP_LOG_BODIES=1.
  const chunks: Buffer[] = [];
  let responseBytes = 0;
  const origWrite = res.write.bind(res) as typeof res.write;
  const origEnd = res.end.bind(res) as typeof res.end;
  (res as unknown as { write: typeof res.write }).write = (chunk: unknown, ...args: unknown[]) => {
    const buf = toBuffer(chunk);
    if (buf) { responseBytes += buf.length; if (LOG_BODIES) chunks.push(buf); }
    return (origWrite as (...a: unknown[]) => boolean)(chunk, ...args);
  };
  (res as unknown as { end: typeof res.end }).end = (chunk?: unknown, ...args: unknown[]) => {
    const buf = toBuffer(chunk);
    if (buf) { responseBytes += buf.length; if (LOG_BODIES) chunks.push(buf); }
    logEvent("mcp.request.end", {
      ...who,
      status: res.statusCode,
      duration_ms: Date.now() - startedAt,
      response_bytes: responseBytes,
      ...(LOG_BODIES ? { body: Buffer.concat(chunks).toString("utf8").slice(0, 600) } : {}),
    });
    return (origEnd as (...a: unknown[]) => Response)(chunk, ...args);
  };

  const server = buildMcpServer();
  try {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    if (LOG_BODIES) {
      // Log what the transport actually sends (before Hono writes it to HTTP)
      const origSend = transport.send.bind(transport);
      transport.send = async (message, options) => {
        console.info("[mcp] transport.send", JSON.stringify(message).slice(0, 400));
        return origSend(message, options);
      };
    }
    await server.connect(transport);
    if (authContext) {
      await withMcpRequestContext({ ...authContext, toolName, requestId }, () => transport.handleRequest(req, res, body));
    } else {
      await transport.handleRequest(req, res, body);
    }
    res.on("close", () => {
      transport.close();
      server.close();
    });
  } catch (err) {
    logEvent("mcp.request.error", { ...who, duration_ms: Date.now() - startedAt, error: (err as Error).message }, "error");
    console.error("[mcp] error:", err);
    if (!res.headersSent) res.status(500).json({ error: "internal_server_error" });
  }
}

function handleMcpGet(_req: Request, res: Response): void {
  res.status(405).set("Allow", "POST").send("Method Not Allowed");
}

// ChatGPT sends MCP requests to root "/" (the URL the user configured, without path)
app.post("/", normalizeMcpAccept, requireBearer, handleMcpPost);
app.get("/", requireBearer, handleMcpGet);

// Also serve at /mcp for clients that append the path themselves
app.post("/mcp", normalizeMcpAccept, requireBearer, handleMcpPost);
app.get("/mcp", requireBearer, handleMcpGet);

// ─── Health ───────────────────────────────────────────────

app.get("/health", (_req, res) => {
  res.json({ status: "ok", server: "asset-management-mcp", transport: "streamable-http-oauth2" });
});

// ─── Start ────────────────────────────────────────────────

app.listen(PORT, "0.0.0.0", () => {
  const base = process.env.BASE_URL ?? `http://localhost:${PORT}`;
  console.log(`\n🚀 Asset Management MCP Server (HTTP + OAuth 2.0)`);
  console.log(`   Port        : ${PORT}`);
  console.log(`   Base URL    : ${base}`);
  console.log(`   MCP endpoint: ${base}/mcp`);
  console.log(`   OAuth disco : ${base}/.well-known/oauth-authorization-server`);
  console.log(`   Also accepts: ${EXTRA_ACCEPTED_RESOURCES.length ? EXTRA_ACCEPTED_RESOURCES.join(", ") : "(none: tokens for this server only)"}\n`);
});
