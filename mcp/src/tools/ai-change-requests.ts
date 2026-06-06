// ============================================================
// AI change request approval buffer tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const riskSchema = z.enum(["low", "medium", "high", "critical"]);
const statusSchema = z.enum(["draft", "pending", "approved", "applied", "rejected", "expired", "failed"]);
const jsonObjectSchema = z.record(z.unknown());

const changeRequestPayloadSchema = z
  .object({
    resource: z.string().min(1).describe("Resource name, for example transactions or monthly_plan_lines"),
    action: z.string().min(1).describe("Action name, for example create or update"),
    risk: riskSchema.optional().default("medium").describe("Operation risk"),
    target_ref: jsonObjectSchema.optional().default({}).describe("Target reference, for example { id: 123 }"),
    input_payload: jsonObjectSchema.optional().default({}).describe("Payload to apply after approval"),
    idempotency_key: z.string().optional().describe("Optional stable key to avoid duplicate requests"),
    status: z.enum(["draft", "pending"]).optional().default("pending").describe("Initial request status"),
  })
  .strict();

export function registerAiChangeRequestTools(server: McpServer): void {
  server.registerTool(
    "ai_change_requests_list",
    {
      title: "List AI change requests",
      description: "Lists pending, approved, applied, rejected, failed, or all AI change requests.",
      inputSchema: z
        .object({
          status: statusSchema.optional().describe("Optional status filter"),
          limit: z.number().int().min(1).max(500).optional().default(50),
          offset: z.number().int().min(0).optional().default(0),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ status, limit = 50, offset = 0 }) => {
      try {
        const params = new URLSearchParams();
        if (status !== undefined) params.append("status", status);
        params.append("limit", String(limit));
        params.append("offset", String(offset));
        const data = await api.get<unknown>(`/ai/change-requests?${params.toString()}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ change_requests: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_change_requests_preview",
    {
      title: "Preview AI change request",
      description: "Builds before/after/diff/validation for a proposed AI change without saving it.",
      inputSchema: changeRequestPayloadSchema.omit({ status: true }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/ai/change-requests/preview", input);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_change_requests_create",
    {
      title: "Create AI change request",
      description: "Creates a draft or pending request that must be approved before apply.",
      inputSchema: changeRequestPayloadSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/ai/change-requests", input);
        return {
          content: [{ type: "text", text: `Created AI change request:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_change_requests_approve",
    {
      title: "Approve AI change request",
      description: "Approves a pending or draft AI change request. Critical requests require a backend step-up token.",
      inputSchema: z
        .object({
          id: z.number().int().min(1).describe("Change request ID"),
          step_up_token: z.string().optional().describe("Required for MFA-protected critical requests"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, step_up_token }) => {
      try {
        const data = await api.post<unknown>(`/ai/change-requests/${id}/approve`, { step_up_token });
        return {
          content: [{ type: "text", text: `Approved AI change request:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_change_requests_apply",
    {
      title: "Apply AI change request",
      description: "Applies an approved AI change request. Fails with conflict if the target changed after preview.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Change request ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/ai/change-requests/${id}/apply`, {});
        return {
          content: [{ type: "text", text: `Applied AI change request:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_change_requests_reject",
    {
      title: "Reject AI change request",
      description: "Rejects a draft, pending, or approved AI change request.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Change request ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/ai/change-requests/${id}/reject`, {});
        return {
          content: [{ type: "text", text: `Rejected AI change request:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_change_requests_refresh_preview",
    {
      title: "Refresh AI change request preview",
      description: "Rebuilds before/after/diff/precondition hash for an existing change request.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Change request ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/ai/change-requests/${id}/refresh-preview`, {});
        return {
          content: [{ type: "text", text: `Refreshed AI change request preview:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
