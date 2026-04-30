// ============================================================
// Life Event Tools — backed by FastAPI /life-events/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

interface LifeEvent {
  id: number;
  name: string;
  target_date: string;
  target_amount: number;
  priority: number;
  note?: string | null;
  progress?: number;
  gap?: number;
  years_remaining?: number;
  status?: string;
  progress_percentage?: number;
}

export function registerLifeEventTools(server: McpServer): void {

  // ── life_events_list ───────────────────────────────────────
  server.registerTool(
    "life_events_list",
    {
      title: "ライフイベント一覧（進捗付き）",
      description: `全ライフイベントを進捗・ギャップ・残り年数・ステータス付きで返します。

Use when: ライフイベントの達成状況を確認したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const data = await api.get<LifeEvent[]>("/life-events/with-progress");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ events: data })
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── life_events_create ─────────────────────────────────────
  server.registerTool(
    "life_events_create",
    {
      title: "ライフイベント作成",
      description: `新しいライフイベント（結婚・住宅購入など）を登録します。

Use when: 新しい目標イベントを追加したいとき`,
      inputSchema: z.object({
        name: z.string().min(1).describe("イベント名"),
        target_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("目標日（YYYY-MM-DD）"),
        target_amount: z.number().min(0).describe("目標金額（円）"),
        priority: z.union([z.literal(1), z.literal(2), z.literal(3)]).describe("優先度（1=高・2=中・3=低）"),
        note: z.string().optional().describe("メモ")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ name, target_date, target_amount, priority, note }) => {
      try {
        const body: Record<string, unknown> = { name, target_date, target_amount, priority };
        if (note !== undefined) body.note = note;
        const data = await api.post<LifeEvent>("/life-events/", body);
        return {
          content: [{ type: "text", text: `Created life event:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── life_events_update ─────────────────────────────────────
  server.registerTool(
    "life_events_update",
    {
      title: "ライフイベント更新",
      description: `既存のライフイベントを更新します。

Use when: ライフイベントの目標・日程・優先度を変更したいとき`,
      inputSchema: z.object({
        id: z.number().int().min(1).describe("ライフイベントID"),
        name: z.string().min(1).optional().describe("イベント名"),
        target_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("目標日（YYYY-MM-DD）"),
        target_amount: z.number().min(0).optional().describe("目標金額（円）"),
        priority: z.union([z.literal(1), z.literal(2), z.literal(3)]).optional().describe("優先度（1=高・2=中・3=低）"),
        note: z.string().optional().describe("メモ")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ id, name, target_date, target_amount, priority, note }) => {
      try {
        const body: Record<string, unknown> = {};
        if (name !== undefined) body.name = name;
        if (target_date !== undefined) body.target_date = target_date;
        if (target_amount !== undefined) body.target_amount = target_amount;
        if (priority !== undefined) body.priority = priority;
        if (note !== undefined) body.note = note;
        const data = await api.put<LifeEvent>(`/life-events/${id}`, body);
        return {
          content: [{ type: "text", text: `Updated life event ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
