// A stand-in for the backend's /auth/mcp endpoints (WP35), so the OAuth scripts
// can drive the MCP server's front door without a database. The backend's own
// rules (codes, rotation, connections) are tested in backend/tests.
import crypto from "node:crypto";
import http from "node:http";
import type { AddressInfo } from "node:net";

export interface FakeBackend {
  url: string;
  requests: Array<{ method: string; path: string; body: Record<string, unknown> }>;
  close(): Promise<void>;
}

export const SIGN_IN = { username: "tester", password: "password123", factor: "123456" };
export const CODE = "code-from-backend";

export async function startFakeBackend(): Promise<FakeBackend> {
  const registrations = new Map<string, Record<string, unknown>>();
  const requests: FakeBackend["requests"] = [];

  function answer(method: string, path: string, body: Record<string, unknown>): [number, unknown] {
    if (method === "POST" && path === "/auth/mcp/clients") {
      const client_id = `mcp_${crypto.randomBytes(16).toString("hex")}`;
      const registration = {
        client_id, client_id_issued_at: Math.floor(Date.now() / 1000), client_name: body.client_name ?? null,
        redirect_uris: body.redirect_uris, grant_types: ["authorization_code", ...((body.grant_types as string[] ?? []).includes("refresh_token") ? ["refresh_token"] : [])],
        response_types: ["code"], token_endpoint_auth_method: "none",
      };
      registrations.set(client_id, registration);
      return [201, registration];
    }
    if (method === "GET" && path.startsWith("/auth/mcp/clients/")) {
      const registration = registrations.get(decodeURIComponent(path.slice("/auth/mcp/clients/".length)));
      return registration ? [200, registration] : [404, { error: "invalid_client" }];
    }
    if (method === "POST" && path === "/auth/mcp/authorize") {
      if (body.username === "setup") return [403, { error: "setup_required" }];
      const ok = body.username === SIGN_IN.username && body.password === SIGN_IN.password && body.factor === SIGN_IN.factor;
      return ok ? [200, { code: CODE, username: SIGN_IN.username }] : [401, { error: "invalid" }];
    }
    if (method === "POST" && path === "/auth/mcp/token") {
      return body.code === CODE || body.refresh_token === "refresh-from-backend"
        ? [200, { access_token: "access-from-backend", token_type: "Bearer", expires_in: 3600, scope: "mcp", refresh_token: "refresh-from-backend" }]
        : [400, { error: "invalid_grant" }];
    }
    return [404, { detail: "Not Found" }];
  }

  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", chunk => chunks.push(chunk));
    req.on("end", () => {
      const text = Buffer.concat(chunks).toString("utf8");
      const body = text ? JSON.parse(text) as Record<string, unknown> : {};
      const path = req.url ?? "/";
      requests.push({ method: req.method ?? "GET", path, body });
      const [status, payload] = answer(req.method ?? "GET", path, body);
      res.writeHead(status, { "Content-Type": "application/json" }).end(JSON.stringify(payload));
    });
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    close: () => new Promise<void>(resolve => server.close(() => resolve())),
  };
}
