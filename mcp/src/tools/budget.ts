// ============================================================
// Budget Management Tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { getBudget, saveBudget } from "../store.js";
import { toStructured } from "../utils.js";

export function registerBudgetTools(server: McpServer): void {

  // ── budget_get ─────────────────────────────────────────────
  server.registerTool(
    "budget_get",
    {
      title: "予算取得",
      description: `現在の月次予算（収支計画）を全カテゴリ取得します。

Returns:
  - phase: 予算フェーズ（1=緊急予備費積立中、2=投資フル稼働）
  - take_home: 月手取り額（円）
  - items[]: カテゴリごとの予算項目
  - summary: 合計・残余など

Use when: 月次予算の確認・実績入力前の確認`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const budget = getBudget();
        const totalPlanned = budget.items.reduce((s, i) => s + i.planned, 0);
        const totalActual = budget.items.filter(i => i.actual !== null).reduce((s, i) => s + (i.actual ?? 0), 0);
        const inputCount = budget.items.filter(i => i.actual !== null).length;

        const result = {
          ...budget,
          summary: {
            total_planned: totalPlanned, total_actual_entered: totalActual,
            items_with_actual: inputCount, items_total: budget.items.length,
            remainder_planned: budget.take_home - totalPlanned
          }
        };

        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── budget_update_item ─────────────────────────────────────
  server.registerTool(
    "budget_update_item",
    {
      title: "予算項目を更新",
      description: `特定カテゴリの予算項目（予定額・実績額・メモ）を更新します。

Args:
  - category (string): 更新対象のカテゴリ名（完全一致）
  - planned (number, optional): 予定額（円）
  - actual (number | null, optional): 実績額（null でリセット）
  - notes (string, optional): メモ
  - min / max (number, optional): 変動費の下限/上限

Use when: 実績額入力・予算計画の修正`,
      inputSchema: z.object({
        category: z.string().min(1).describe("カテゴリ名（完全一致）"),
        planned: z.number().int().min(0).optional().describe("予定額（円）"),
        actual: z.number().int().min(0).nullable().optional().describe("実績額（円、null でリセット）"),
        notes: z.string().optional().describe("メモ"),
        min: z.number().int().min(0).optional().describe("変動費の下限（円）"),
        max: z.number().int().min(0).optional().describe("変動費の上限（円）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ category, planned, actual, notes, min, max }) => {
      try {
        const budget = getBudget();
        const item = budget.items.find(i => i.category === category);
        if (!item) {
          return { content: [{ type: "text", text: `Error: カテゴリ "${category}" が見つかりません。\n利用可能: ${budget.items.map(i => i.category).join(", ")}` }] };
        }

        if (planned !== undefined) item.planned = planned;
        if (actual !== undefined) item.actual = actual;
        if (notes !== undefined) item.notes = notes;
        if (min !== undefined) item.min = min;
        if (max !== undefined) item.max = max;

        saveBudget(budget);
        return {
          content: [{ type: "text", text: `✅ "${category}" を更新しました。\n\n${JSON.stringify(budget, null, 2)}` }],
          structuredContent: toStructured(budget)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── budget_add_item ────────────────────────────────────────
  server.registerTool(
    "budget_add_item",
    {
      title: "予算項目を追加",
      description: `新しい予算カテゴリを追加します。

Use when: 新しい支出カテゴリを追加したいとき`,
      inputSchema: z.object({
        category: z.string().min(1).describe("カテゴリ名"),
        planned: z.number().int().min(0).describe("予定額（円）"),
        notes: z.string().optional().describe("メモ"),
        min: z.number().int().min(0).optional().describe("変動費の下限（円）"),
        max: z.number().int().min(0).optional().describe("変動費の上限（円）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ category, planned, notes, min, max }) => {
      try {
        const budget = getBudget();
        if (budget.items.some(i => i.category === category)) {
          return { content: [{ type: "text", text: `Error: カテゴリ "${category}" は既に存在します。budget_update_item を使用してください。` }] };
        }
        budget.items.push({ category, planned, actual: null, notes, min, max });
        saveBudget(budget);
        return {
          content: [{ type: "text", text: `✅ "${category}" を追加しました。\n\n${JSON.stringify(budget, null, 2)}` }],
          structuredContent: toStructured(budget)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── budget_cashflow ────────────────────────────────────────
  server.registerTool(
    "budget_cashflow",
    {
      title: "キャッシュフロー分析",
      description: `月次のキャッシュフローを分析します。予定・実績それぞれの残余を計算します。

Use when: 月末の収支確認・予算と実績の乖離チェック`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const budget = getBudget();
        const items = budget.items;
        const investmentKeywords = ["NISA", "DC", "持株", "投資", "積立"];
        const isInvestment = (cat: string) => investmentKeywords.some(k => cat.includes(k));

        const investItems = items.filter(i => isInvestment(i.category));
        const livingItems = items.filter(i => !isInvestment(i.category));

        const plannedLiving = livingItems.reduce((s, i) => s + i.planned, 0);
        const plannedInvest = investItems.reduce((s, i) => s + i.planned, 0);
        const plannedTotal = plannedLiving + plannedInvest;
        const actualLiving = livingItems.filter(i => i.actual !== null).reduce((s, i) => s + (i.actual ?? 0), 0);
        const actualInvest = investItems.filter(i => i.actual !== null).reduce((s, i) => s + (i.actual ?? 0), 0);
        const savingsRate = plannedInvest > 0 ? +(plannedInvest / budget.take_home * 100).toFixed(1) : 0;

        const result = {
          as_of: budget.as_of,
          income: budget.take_home,
          planned: { living_expenses: plannedLiving, investments: plannedInvest, total: plannedTotal, remainder: budget.take_home - plannedTotal },
          actual_entered: { living_expenses: actualLiving, investments: actualInvest, total: actualLiving + actualInvest, note: "実績未入力の項目は含まれません" },
          savings_rate_pct: savingsRate,
          items_breakdown: items.map(i => ({ category: i.category, planned: i.planned, actual: i.actual, diff: i.actual !== null ? i.actual - i.planned : null }))
        };

        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
