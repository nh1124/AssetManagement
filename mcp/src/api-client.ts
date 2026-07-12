// HTTP client: uses MCP token exchange in HTTP mode and fixed credentials only for stdio fallback.

import { AsyncLocalStorage } from "node:async_hooks";

const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const BACKEND_USERNAME = process.env.BACKEND_USERNAME ?? "";
const BACKEND_PASSWORD = process.env.BACKEND_PASSWORD ?? "";

export interface McpRequestContext {
  mcpAccessToken: string;
  mcpClientId: string;
  username: string;
  backendClientId: number;
  toolName?: string;
}

const requestContext = new AsyncLocalStorage<McpRequestContext>();
let stdioToken: string | null = null;
const mcpTokenCache = new Map<string, string>();

export function withMcpRequestContext<T>(context: McpRequestContext, fn: () => Promise<T>): Promise<T> {
  return requestContext.run(context, fn);
}

async function login(): Promise<string> {
  const res = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: BACKEND_USERNAME, password: BACKEND_PASSWORD }),
  });
  if (!res.ok) throw new Error(`Login failed: ${res.status} ${await res.text()}`);
  const data = await res.json() as { access_token?: string; mfa_required?: boolean };
  if (data.mfa_required || !data.access_token) {
    throw new Error("Backend login requires MFA; configure a non-interactive MCP credential flow before using this account");
  }
  return data.access_token;
}

async function exchangeMcpToken(context: McpRequestContext): Promise<string> {
  const cached = mcpTokenCache.get(context.mcpAccessToken);
  if (cached) return cached;

  const res = await fetch(`${BACKEND_URL}/auth/mcp/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mcp_access_token: context.mcpAccessToken }),
  });
  if (!res.ok) throw new Error(`MCP token exchange failed: ${res.status} ${await res.text()}`);
  const data = await res.json() as { access_token?: string };
  if (!data.access_token) throw new Error("MCP token exchange did not return an access token");
  mcpTokenCache.set(context.mcpAccessToken, data.access_token);
  return data.access_token;
}

async function getToken(): Promise<string> {
  const context = requestContext.getStore();
  if (context) return exchangeMcpToken(context);

  if (!stdioToken) stdioToken = await login();
  return stdioToken;
}

function contextHeaders(context: McpRequestContext | undefined): Record<string, string> {
  return context ? {
    "X-MCP-Client-Id": context.mcpClientId,
    "X-MCP-Username": context.username,
    "X-MCP-Backend-Client-Id": String(context.backendClientId),
    ...(context.toolName ? { "X-MCP-Tool-Name": context.toolName } : {}),
  } : {};
}

function methodOf(init: RequestInit): string {
  return String(init.method ?? "GET").toUpperCase();
}

function isWriteRequest(path: string, init: RequestInit): boolean {
  const method = methodOf(init);
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return false;
  if (path.startsWith("/auth/")) return false;
  if (path.startsWith("/ai/change-requests")) return false;
  if (path.startsWith("/ai/execution-settings")) return false;
  if (path === "/ai/evaluate") return false;
  if (path.startsWith("/api/analyze")) return false;
  if (path.includes("/preview")) return false;
  if (path.includes("/monte-carlo")) return false;
  return true;
}

async function enforceMcpWriteMode(path: string, init: RequestInit, token: string, context: McpRequestContext | undefined): Promise<void> {
  if (!isWriteRequest(path, init)) return;
  const res = await fetch(`${BACKEND_URL}/ai/execution-settings`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...contextHeaders(context),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(
      `Cannot verify MCP write mode; refusing ${methodOf(init)} ${path} (${res.status}): ${body}`,
    );
  }
  const settings = await res.json() as { mcp_write_mode?: string };
  if (settings.mcp_write_mode === "change_request") {
    throw new Error(
      "Change request mode is enabled in Settings. This MCP write tool is not applying a direct write. " +
      "Use an approval-buffer-backed operation or create an AI change request and review it in Approval Inbox.",
    );
  }
}

async function request<T>(path: string, init: RequestInit = {}, authRetried = false): Promise<T> {
  const token = await getToken();
  const context = requestContext.getStore();
  await enforceMcpWriteMode(path, init, token, context);
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...contextHeaders(context),
      ...((init.headers ?? {}) as Record<string, string>),
    },
  });
  if (res.status === 401) {
    const body = await res.text();
    if (authRetried) {
      throw new Error(`API ${init.method ?? "GET"} ${path} -> 401 after one authentication retry: ${body}`);
    }
    if (context) {
      mcpTokenCache.delete(context.mcpAccessToken);
    } else {
      stdioToken = await login();
    }
    return request<T>(path, init, true);
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${init.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) as T : undefined as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
