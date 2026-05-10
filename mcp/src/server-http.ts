// ============================================================
// Asset Management MCP Server - HTTP (OAuth 2.0)
// ============================================================

import express, { type Request, type Response, type NextFunction } from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { buildMcpServer } from "./server.js";
import {
  JWT_SECRET,
  getDiscoveryMetadata,
  registerClient,
  resolveClient,
  createAuthCode,
  exchangeCodeForTokens,
  refreshAccessToken,
  validateAccessToken,
} from "./auth.js";

const PORT = parseInt(process.env.PORT ?? "3000");
const MCP_PASSWORD = process.env.MCP_PASSWORD ?? "";
const MCP_USERNAME = process.env.MCP_USERNAME?.trim() || "admin";

if (!MCP_PASSWORD) {
  console.warn("⚠️  MCP_PASSWORD is not set. Set it in your .env file before production use.");
}

// ─── Issuer / Resource helpers ────────────────────────────

function buildOAuthIssuer(req: Request): string {
  // Prefer explicitly configured base URL
  const configured = process.env.BASE_URL?.trim();
  if (configured && configured.startsWith("https://")) return configured;

  // Derive from forwarded headers (Cloudflare Tunnel sets these)
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

// CORS
app.use((_req: Request, res: Response, next: NextFunction) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Mcp-Session-Id, Last-Event-ID");
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

app.post("/register", (req, res) => {
  const body = req.body as Record<string, unknown>;
  const client = registerClient(body);
  console.info("[oauth] client registered", {
    client_id: client.client_id,
    client_name: client.client_name,
    grant_types: client.grant_types,
  });
  res.status(201).json({
    client_id: client.client_id,
    client_id_issued_at: client.client_id_issued_at,
    client_name: client.client_name,
    redirect_uris: client.redirect_uris,
    grant_types: client.grant_types,
    response_types: client.response_types,
    token_endpoint_auth_method: client.token_endpoint_auth_method,
  });
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
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">📊</div>
    <h1>Asset Management MCP</h1>
    <div class="app-label">接続アプリ: <strong>${esc(params.client_name ?? params.client_id)}</strong></div>
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
      <button type="submit">ログイン &amp; 許可</button>
    </form>
    <p class="note">スコープ: ${esc(params.scope)}</p>
  </div>
</body>
</html>`;
}

app.get("/authorize", async (req, res) => {
  const q = req.query as Record<string, string>;
  const { response_type, client_id, redirect_uri, code_challenge, code_challenge_method, state, scope } = q;
  const resource = q.resource || buildCanonicalMcpResource(req);

  if (response_type !== "code") { res.status(400).json({ error: "unsupported_response_type" }); return; }
  if (!client_id || !redirect_uri || !code_challenge) { res.status(400).json({ error: "invalid_request" }); return; }

  const client = await resolveClient(client_id);
  if (!client) { res.status(400).json({ error: "invalid_client" }); return; }
  if (!client.redirect_uris.includes(redirect_uri)) { res.status(400).json({ error: "invalid_redirect_uri" }); return; }

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
  const { response_type, client_id, redirect_uri, code_challenge, code_challenge_method, state, scope, username, password } = b;
  const resource = b.resource || buildCanonicalMcpResource(req);

  if (response_type !== "code") { res.status(400).json({ error: "unsupported_response_type" }); return; }
  if (!client_id || !redirect_uri || !code_challenge) { res.status(400).json({ error: "invalid_request" }); return; }

  const client = await resolveClient(client_id);
  if (!client) { res.status(400).json({ error: "invalid_client" }); return; }
  if (!client.redirect_uris.includes(redirect_uri)) { res.status(400).json({ error: "invalid_redirect_uri" }); return; }

  const credentialsValid = MCP_PASSWORD && username === MCP_USERNAME && password === MCP_PASSWORD;
  if (!credentialsValid) {
    res.status(401).setHeader("Content-Type", "text/html; charset=utf-8").send(renderLoginForm({
      client_id,
      client_name: client.client_name,
      redirect_uri,
      code_challenge,
      code_challenge_method: code_challenge_method ?? "S256",
      state,
      scope: scope ?? "mcp",
      resource,
      response_type,
    }, "ユーザー名またはパスワードが正しくありません"));
    return;
  }

  console.info("[oauth] authorize POST success", { client_id, username, resource });

  const code = createAuthCode({
    client_id,
    redirect_uri,
    code_challenge,
    code_challenge_method: code_challenge_method ?? "S256",
    scope: scope ?? "mcp",
    state,
    resource,
    allow_refresh_token: client.grant_types.includes("refresh_token"),
    username,
  });

  const redirectUrl = new URL(redirect_uri);
  redirectUrl.searchParams.set("code", code);
  if (state) redirectUrl.searchParams.set("state", state);
  res.redirect(302, redirectUrl.toString());
});

// ─── Token Endpoint ───────────────────────────────────────

app.post("/token", (req, res) => {
  const b = req.body as Record<string, string>;
  const { grant_type } = b;
  const canonical_resource = buildCanonicalMcpResource(req);

  console.info("[oauth] token request", {
    grant_type: grant_type || "(missing)",
    client_id: b.client_id || "(missing)",
    has_code: !!b.code,
    has_refresh_token: !!b.refresh_token,
    resource: b.resource || "(missing)",
  });

  if (grant_type === "authorization_code") {
    const { code, redirect_uri, client_id, code_verifier } = b;
    const resource = b.resource || undefined;

    if (!code || !redirect_uri || !client_id || !code_verifier) {
      res.status(400).json({ error: "invalid_request" }); return;
    }

    const tokens = exchangeCodeForTokens({ code, client_id, redirect_uri, code_verifier, resource, canonical_resource });
    if (!tokens) {
      console.warn("[oauth] token exchange failed", { grant_type: "authorization_code", client_id });
      res.status(400).json({ error: "invalid_grant" }); return;
    }

    console.info("[oauth] access token issued", { grant_type: "authorization_code", client_id, has_refresh: !!tokens.refresh_token });
    res.json(tokens);

  } else if (grant_type === "refresh_token") {
    const { refresh_token, client_id } = b;

    if (!refresh_token || !client_id) {
      res.status(400).json({ error: "invalid_request" }); return;
    }

    const tokens = refreshAccessToken({ client_id, refresh_token, canonical_resource });
    if (!tokens) {
      console.warn("[oauth] refresh token exchange failed", { client_id });
      res.status(400).json({ error: "invalid_grant" }); return;
    }

    console.info("[oauth] access token refreshed", { client_id });
    res.json(tokens);

  } else {
    res.status(400).json({ error: "unsupported_grant_type" });
  }
});

// ─── Auth Middleware ───────────────────────────────────────

function requireBearer(req: Request, res: Response, next: NextFunction): void {
  const issuer = buildOAuthIssuer(req);
  const auth = req.headers.authorization;
  if (!auth?.startsWith("Bearer ")) {
    console.warn("[mcp] missing Bearer token", { method: req.method, path: req.path });
    res.setHeader("WWW-Authenticate", `Bearer realm="${issuer}", scope="mcp"`).status(401).json({ error: "unauthorized" });
    return;
  }
  if (!validateAccessToken(auth.slice(7))) {
    console.warn("[mcp] invalid Bearer token", { method: req.method, path: req.path, token_prefix: auth.slice(7, 20) });
    res.setHeader("WWW-Authenticate", `Bearer realm="${issuer}", error="invalid_token"`).status(401).json({ error: "invalid_token" });
    return;
  }
  next();
}

// ─── MCP Endpoint ─────────────────────────────────────────

// Ensure Accept header has both application/json and text/event-stream (required by MCP SDK).
// Some MCP clients (e.g. ChatGPT) omit text/event-stream when using enableJsonResponse mode.
app.use("/mcp", (req: Request, _res: Response, next: NextFunction) => {
  if (req.method === "POST") {
    const accept = req.headers.accept ?? "";
    if (!accept.includes("text/event-stream")) {
      req.headers.accept = accept ? `${accept}, text/event-stream` : "application/json, text/event-stream";
    }
    console.info("[mcp] POST request", {
      accept: req.headers.accept,
      has_auth: !!req.headers.authorization,
      content_type: req.headers["content-type"],
    });
  }
  next();
});

app.post("/mcp", requireBearer, async (req, res) => {
  const server = buildMcpServer();
  try {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
    res.on("close", () => {
      transport.close();
      server.close();
    });
  } catch (err) {
    console.error("[mcp] error:", err);
    if (!res.headersSent) res.status(500).json({ error: "internal_server_error" });
  }
});

app.get("/mcp", requireBearer, (_req, res) => {
  res.status(405).set("Allow", "POST").send("Method Not Allowed");
});

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
  console.log(`   OAuth disco : ${base}/.well-known/oauth-authorization-server\n`);
});
