// ============================================================
// Life Event tools backed by FastAPI /life-events/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

interface LifeEvent {
  id: number;
  name: string;
  start_date?: string | null;
  target_date: string;
  target_amount: number;
  priority: number;
  note?: string | null;
  active_plan_basis?: string;
  active_plan_label?: string | null;
  plan_status_override?: string | null;
  current_funded?: number;
  projected_amount?: number;
  gap?: number;
  funded_percentage?: number;
  plan_expected_amount?: number;
  plan_gap?: number;
  plan_status?: string;
  plan_progress_percentage?: number;
  years_remaining?: number;
  status?: string;
  progress_percentage?: number;
}

const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

const lifeEventCreateSchema = z
  .object({
    name: z.string().min(1).describe("Life event name"),
    start_date: dateSchema.optional().describe("Optional start date, YYYY-MM-DD"),
    target_date: dateSchema.describe("Target date, YYYY-MM-DD"),
    target_amount: z.number().min(0).describe("Target amount"),
    priority: z.number().int().min(1).max(3).describe("Priority: 1=high, 2=medium, 3=low"),
    note: z.string().optional().describe("Optional note"),
    active_plan_basis: z.string().optional().describe("Active operating plan basis"),
    active_plan_label: z.string().nullable().optional().describe("Active operating plan label"),
    plan_status_override: z.string().nullable().optional().describe("Optional manual plan status override"),
  })
  .strict();

const lifeEventUpdateSchema = lifeEventCreateSchema
  .partial()
  .extend({
    id: z.number().int().min(1).describe("Life event ID"),
  })
  .strict();

async function getLifeEventsWithProgress(): Promise<LifeEvent[]> {
  return api.get<LifeEvent[]>("/life-events/with-progress");
}

export function registerLifeEventTools(server: McpServer): void {
  server.registerTool(
    "life_events_list",
    {
      title: "List life events",
      description: "Returns all life events with progress, projected amount, funded amount, gap, years remaining, and status.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await getLifeEventsWithProgress();
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ events: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "life_events_get",
    {
      title: "Get life event",
      description: "Returns one life event by ID, including progress fields when available.",
      inputSchema: z
        .object({
          id: z.number().int().min(1).describe("Life event ID"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const events = await getLifeEventsWithProgress();
        const data = events.find((event) => event.id === id);
        if (!data) {
          return { content: [{ type: "text", text: `Error: Life event ${id} not found` }] };
        }
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
    "life_events_create",
    {
      title: "Create life event",
      description: "Creates a new life event goal. The backend will also create default milestones and a linked capsule.",
      inputSchema: lifeEventCreateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ name, start_date, target_date, target_amount, priority, note, active_plan_basis, active_plan_label, plan_status_override }) => {
      try {
        const body: Record<string, unknown> = { name, target_date, target_amount, priority };
        if (start_date !== undefined) body.start_date = start_date;
        if (note !== undefined) body.note = note;
        if (active_plan_basis !== undefined) body.active_plan_basis = active_plan_basis;
        if (active_plan_label !== undefined) body.active_plan_label = active_plan_label;
        if (plan_status_override !== undefined) body.plan_status_override = plan_status_override;
        const data = await api.post<LifeEvent>("/life-events/", body);
        return {
          content: [{ type: "text", text: `Created life event:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "life_events_update",
    {
      title: "Update life event",
      description: "Updates an existing life event's name, dates, target amount, priority, or note.",
      inputSchema: lifeEventUpdateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, name, start_date, target_date, target_amount, priority, note, active_plan_basis, active_plan_label, plan_status_override }) => {
      try {
        const body: Record<string, unknown> = {};
        if (name !== undefined) body.name = name;
        if (start_date !== undefined) body.start_date = start_date;
        if (target_date !== undefined) body.target_date = target_date;
        if (target_amount !== undefined) body.target_amount = target_amount;
        if (priority !== undefined) body.priority = priority;
        if (note !== undefined) body.note = note;
        if (active_plan_basis !== undefined) body.active_plan_basis = active_plan_basis;
        if (active_plan_label !== undefined) body.active_plan_label = active_plan_label;
        if (plan_status_override !== undefined) body.plan_status_override = plan_status_override;
        const data = await api.put<LifeEvent>(`/life-events/${id}`, body);
        return {
          content: [{ type: "text", text: `Updated life event ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "life_events_delete",
    {
      title: "Delete life event",
      description: "Deletes a life event. If linked capsules have a positive balance, transfer_account_id is required by the backend.",
      inputSchema: z
        .object({
          id: z.number().int().min(1).describe("Life event ID"),
          transfer_account_id: z.number().int().min(1).optional().describe("Destination account ID for positive capsule balances"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id, transfer_account_id }) => {
      try {
        const query = transfer_account_id !== undefined ? `?transfer_account_id=${transfer_account_id}` : "";
        const data = await api.delete<unknown>(`/life-events/${id}${query}`);
        return {
          content: [{ type: "text", text: `Deleted life event ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
