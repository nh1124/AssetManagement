// ============================================================
// Asset Management MCP Server - HTTP (OAuth 2.0)
// ============================================================

import express, { type Request, type Response, type NextFunction } from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { buildMcpServer } from "./server.js";
import {
  BASE_URL, getDiscoveryMetadata, registerClient, getClient,
  createAuthCode, exchangeCodeForTokens, refreshAccessToken, validateAccessToken,
} from "./auth.js";

const PORT = parseInt(process.env.PORT ?? "3000");
const MCP_PASSWORD = process.env.MCP_PASSWORD ?? "";

if (!MCP_PASSWORD) {
  console.warn("⚠️  MCP_PASSWORD is not set. Set it in your .env file before production use.");
}

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
  if (req.method === "OPTIONS") {
    res.sendStatus(204);
    return;
  }
  next();
});

// ─── OAuth 2.0 Endpoints ──────────────────────────────────

app.get("/.well-known/oauth-authorization-server", (_req, res) => {
  res.json(getDiscoveryMetadata());
});

app.post("/register", (req, res) => {
  const client = registerClient(req.body as Record<string, unknown>);
  res.status(201).json(client);
});

app.get("/authorize", (req, res) => {
  const { client_id, redirect_uri, code_challenge, code_challenge_method, state, scope, response_type } = req.query as Record<string, string>;

  if (response_type !== "code") { res.status(400).json({ error: "unsupported_response_type" }); return; }
  if (!client_id || !redirect_uri || !code_challenge) { res.status(400).json({ error: "invalid_request" }); return; }

  const client = getClient(client_id);
  if (!client) { res.status(400).json({ error: "invalid_client" }); return; }

  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

  res.setHeader("Content-Type", "text/html; charset=utf-8").send(`<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Asset Management MCP - ログイン</title>
  <style>
    *,*::before,*::after{box-sizing:border-box}
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f0f2f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem}
    .card{background:#fff;padding:2rem;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);width:100%;max-width:360px}
    .logo{font-size:2rem;text-align:center;margin-bottom:.5rem}
    h1{font-size:1.1rem;color:#111;text-align:center;margin:0 0 .25rem}
    .app-label{font-size:.8rem;color:#666;text-align:center;margin-bottom:1.75rem}
    label{display:block;font-size:.85rem;font-weight:600;color:#333;margin-bottom:.4rem}
    input[type=password]{width:100%;padding:.75rem 1rem;border:1.5px solid #ddd;border-radius:10px;font-size:1rem;outline:none}
    input[type=password]:focus{border-color:#0070f3}
    button{width:100%;padding:.8rem;background:#0070f3;color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;margin-top:1rem}
    button:hover{background:#005ed3}
    .note{font-size:.75rem;color:#888;text-align:center;margin-top:1rem}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">📊</div>
    <h1>Asset Management MCP</h1>
    <div class="app-label">接続アプリ: <strong>${esc(client.client_name ?? client_id)}</strong></div>
    <form method="POST" action="/authorize">
      <input type="hidden" name="client_id"             value="${esc(client_id)}">
      <input type="hidden" name="redirect_uri"          value="${esc(redirect_uri)}">
      <input type="hidden" name="code_challenge"        value="${esc(code_challenge)}">
      <input type="hidden" name="code_challenge_method" value="${esc(code_challenge_method ?? "S256")}">
      <input type="hidden" name="state"                 value="${esc(state ?? "")}">
      <input type="hidden" name="scope"                 value="${esc(scope ?? "mcp")}">
      <label for="pw">パスワード</label>
      <input type="password" id="pw" name="password" placeholder="••••••••" autofocus required>
      <button type="submit">ログイン &amp; 許可</button>
    </form>
    <p class="note">スコープ: ${esc(scope ?? "mcp")}</p>
  </div>
</body>
</html>`);
});

app.post("/authorize", (req, res) => {
  const { client_id, redirect_uri, code_challenge, code_challenge_method, state, scope, password } = req.body as Record<string, string>;

  if (!MCP_PASSWORD || password !== MCP_PASSWORD) {
    res.status(401).setHeader("Content-Type", "text/html; charset=utf-8").send(
      `<html><body style="font-family:sans-serif;padding:2rem"><h2>❌ パスワードが正しくありません</h2><a href="javascript:history.back()">← 戻る</a></body></html>`
    );
    return;
  }

  const client = getClient(client_id);
  if (!client) { res.status(400).json({ error: "invalid_client" }); return; }

  const code = createAuthCode({ client_id, redirect_uri, code_challenge, code_challenge_method: code_challenge_method ?? "S256", scope: scope ?? "mcp", state });
  const redirectUrl = new URL(redirect_uri);
  redirectUrl.searchParams.set("code", code);
  if (state) redirectUrl.searchParams.set("state", state);
  res.redirect(302, redirectUrl.toString());
});

app.post("/token", (req, res) => {
  const { grant_type, code, redirect_uri, client_id, code_verifier, refresh_token } = req.body as Record<string, string>;

  if (grant_type === "authorization_code") {
    if (!code || !redirect_uri || !client_id || !code_verifier) { res.status(400).json({ error: "invalid_request" }); return; }
    const tokens = exchangeCodeForTokens({ code, client_id, redirect_uri, code_verifier });
    if (!tokens) { res.status(400).json({ error: "invalid_grant" }); return; }
    res.json(tokens);
  } else if (grant_type === "refresh_token") {
    if (!refresh_token) { res.status(400).json({ error: "invalid_request" }); return; }
    const tokens = refreshAccessToken(refresh_token);
    if (!tokens) { res.status(400).json({ error: "invalid_grant" }); return; }
    res.json(tokens);
  } else {
    res.status(400).json({ error: "unsupported_grant_type" });
  }
});

// ─── Auth Middleware ───────────────────────────────────────

function requireBearer(req: Request, res: Response, next: NextFunction): void {
  const auth = req.headers.authorization;
  if (!auth?.startsWith("Bearer ")) {
    res.setHeader("WWW-Authenticate", `Bearer realm="${BASE_URL}", scope="mcp"`).status(401).json({ error: "unauthorized" });
    return;
  }
  if (!validateAccessToken(auth.slice(7))) {
    res.setHeader("WWW-Authenticate", `Bearer realm="${BASE_URL}", error="invalid_token"`).status(401).json({ error: "invalid_token" });
    return;
  }
  next();
}

// ─── MCP Endpoint (Stateless) ─────────────────────────────

app.post("/mcp", requireBearer, async (req, res) => {
  const server = buildMcpServer();
  try {
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error("[MCP] Error:", err);
    if (!res.headersSent) res.status(500).json({ error: "internal_server_error" });
  } finally {
    res.on("finish", () => void server.close());
  }
});

app.get("/mcp", requireBearer, (_req, res) => {
  res.status(405).json({ error: "method_not_allowed", hint: "Use POST /mcp" });
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", server: "asset-management-mcp", transport: "streamable-http-oauth2" });
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`\n🚀 Asset Management MCP Server (HTTP + OAuth 2.0)`);
  console.log(`   Port        : ${PORT}`);
  console.log(`   Base URL    : ${BASE_URL}`);
  console.log(`   MCP endpoint: ${BASE_URL}/mcp`);
  console.log(`   OAuth disco : ${BASE_URL}/.well-known/oauth-authorization-server`);
  console.log(`   Health      : ${BASE_URL}/health\n`);
});
