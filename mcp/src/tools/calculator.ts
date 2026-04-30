// ============================================================
// Financial Calculator Tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { toStructured } from "../utils.js";
import type { FutureValueResult, ProjectionResult } from "../types.js";

// Compound interest future value (annuity due): FV = PMT * [(1+r)^n - 1] / r * (1+r)
function calcFV(monthlyAmount: number, annualRatePct: number, years: number): number {
  if (annualRatePct === 0) return monthlyAmount * 12 * years;
  const r = annualRatePct / 100 / 12;
  const n = years * 12;
  return monthlyAmount * ((Math.pow(1 + r, n) - 1) / r) * (1 + r);
}

export function registerCalculatorTools(server: McpServer): void {

  // ── calc_future_value ──────────────────────────────────────
  server.registerTool(
    "calc_future_value",
    {
      title: "将来価値シミュレーション",
      description: `月額積立・想定利回り・期間から将来価値（複利）を計算します。

Use when: 将来の資産額をシミュレーションしたいとき`,
      inputSchema: z.object({
        monthly_amount: z.number().int().min(1).describe("月額積立金額（円）"),
        annual_rate_pct: z.number().min(0).max(30).describe("年率リターン（%）"),
        years: z.number().int().min(1).max(60).describe("積立期間（年）"),
        label: z.string().optional().describe("シミュレーション名")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ monthly_amount, annual_rate_pct, years, label }) => {
      try {
        const fv = calcFV(monthly_amount, annual_rate_pct, years);
        const contributed = monthly_amount * 12 * years;
        const gain = fv - contributed;

        const result: FutureValueResult & { label?: string } = {
          label, monthly_amount, annual_rate_pct, years,
          future_value: Math.round(fv), total_contributed: contributed,
          total_gain: Math.round(gain), gain_ratio_pct: +(gain / contributed * 100).toFixed(1)
        };

        return {
          content: [{ type: "text", text: `📈 ${label ?? "シミュレーション結果"}\n月額: ${monthly_amount.toLocaleString()}円 × ${years}年 @ ${annual_rate_pct}%\n将来価値: ${(Math.round(fv) / 10000).toFixed(0)}万円\n元本: ${(contributed / 10000).toFixed(0)}万円\n運用益: ${(Math.round(gain) / 10000).toFixed(0)}万円（+${result.gain_ratio_pct}%）\n\n${JSON.stringify(result, null, 2)}` }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── calc_future_value_multi ────────────────────────────────
  server.registerTool(
    "calc_future_value_multi",
    {
      title: "複数シナリオ比較",
      description: `同一条件で複数の年率シナリオを一括比較します（悲観/中立/楽観）。

Use when: 利回り別のシナリオ比較`,
      inputSchema: z.object({
        monthly_amount: z.number().int().min(1).describe("月額積立金額（円）"),
        years: z.number().int().min(1).max(60).describe("積立期間（年）"),
        scenarios: z.array(z.object({
          label: z.string().describe("シナリオ名（例: 悲観3%）"),
          rate_pct: z.number().min(0).max(30).describe("年率（%）")
        })).min(1).max(10).describe("シナリオリスト")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ monthly_amount, years, scenarios }) => {
      try {
        const contributed = monthly_amount * 12 * years;
        const results = scenarios.map(s => {
          const fv = Math.round(calcFV(monthly_amount, s.rate_pct, years));
          const gain = fv - contributed;
          return { label: s.label, rate_pct: s.rate_pct, future_value: fv, future_value_man: Math.round(fv / 10000), total_gain: gain, gain_ratio_pct: +(gain / contributed * 100).toFixed(1) };
        });

        const table = results.map(r => `  ${r.label.padEnd(12)} ${(r.future_value_man + "万円").padStart(8)}  (+${r.gain_ratio_pct}%)`).join("\n");
        const result = { monthly_amount, years, total_contributed: contributed, scenarios: results };

        return {
          content: [{ type: "text", text: `📊 シナリオ比較（月額${monthly_amount.toLocaleString()}円 × ${years}年）\n元本: ${(contributed / 10000).toFixed(0)}万円\n\n${table}\n\n${JSON.stringify(result, null, 2)}` }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── calc_project_all ───────────────────────────────────────
  server.registerTool(
    "calc_project_all",
    {
      title: "全口座合算プロジェクション",
      description: `NISA・DC・持株会の合算将来価値を試算します。月額は明示的に指定してください。

Use when: リタイア時・ライフイベント時の資産見込みを確認したいとき`,
      inputSchema: z.object({
        age: z.number().int().min(18).max(80).optional().default(27).describe("現在の年齢（デフォルト27）"),
        target_age: z.number().int().min(28).max(80).describe("目標年齢"),
        nisa_monthly: z.number().int().min(0).optional().default(100000).describe("NISA月額積立（円、デフォルト100000）"),
        dc_monthly: z.number().int().min(0).optional().default(25000).describe("DC月額拠出（円、デフォルト25000）"),
        holdings_monthly: z.number().int().min(0).optional().default(50000).describe("持株会月額（円、デフォルト50000）"),
        nisa_rate_pct: z.number().min(0).max(20).optional().default(5.0).describe("NISA想定利回り（%、デフォルト5.0）"),
        dc_rate_pct: z.number().min(0).max(20).optional().default(5.0).describe("DC想定利回り（%、デフォルト5.0）"),
        holdings_rate_pct: z.number().min(0).max(20).optional().default(3.0).describe("持株会想定利回り（%、デフォルト3.0）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ age = 27, target_age, nisa_monthly = 100000, dc_monthly = 25000, holdings_monthly = 50000, nisa_rate_pct = 5.0, dc_rate_pct = 5.0, holdings_rate_pct = 3.0 }) => {
      try {
        const yearsRemaining = target_age - age;
        if (yearsRemaining <= 0) {
          return { content: [{ type: "text", text: `Error: target_age (${target_age}) は現在の年齢 (${age}) より大きい値を指定してください。` }] };
        }

        const accounts = [
          { account: "NISA（積立）", monthly_amount: nisa_monthly, annual_rate_pct: nisa_rate_pct },
          { account: "企業型DC", monthly_amount: dc_monthly, annual_rate_pct: dc_rate_pct },
          { account: "NTT持株会", monthly_amount: holdings_monthly, annual_rate_pct: holdings_rate_pct }
        ];

        const projections = accounts.map(a => ({
          account: a.account, monthly_amount: a.monthly_amount, annual_rate_pct: a.annual_rate_pct,
          future_value: Math.round(calcFV(a.monthly_amount, a.annual_rate_pct, yearsRemaining))
        }));

        const totalFV = projections.reduce((s, a) => s + a.future_value, 0);
        const result: ProjectionResult = { target_age, years_remaining: yearsRemaining, projections, total_future_value: totalFV };
        const lines = projections.map(a => `  ${a.account.padEnd(14)} ${(a.future_value / 10000).toFixed(0).padStart(6)}万円 @ ${a.annual_rate_pct}%`).join("\n");

        return {
          content: [{ type: "text", text: `🎯 ${target_age}歳時点（${yearsRemaining}年後）の資産見込み\n\n${lines}\n  ${"─".repeat(30)}\n  合計             ${(totalFV / 10000).toFixed(0).padStart(6)}万円\n\n${JSON.stringify(result, null, 2)}` }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── calc_dc_tax_saving ─────────────────────────────────────
  server.registerTool(
    "calc_dc_tax_saving",
    {
      title: "DC節税効果計算",
      description: `企業型DCの年間節税効果を計算します（所得税・住民税の軽減額）。

Use when: DCの節税メリットを確認したいとき`,
      inputSchema: z.object({
        monthly_contribution: z.number().int().min(1).describe("月額拠出（円）"),
        income_tax_rate_pct: z.number().min(0).max(45).optional().default(10).describe("所得税率（%、デフォルト10）"),
        resident_tax_rate_pct: z.number().min(0).max(20).optional().default(10).describe("住民税率（%、デフォルト10）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ monthly_contribution, income_tax_rate_pct = 10, resident_tax_rate_pct = 10 }) => {
      try {
        const monthly = monthly_contribution;
        const annual = monthly * 12;
        const savingIncome = Math.round(annual * income_tax_rate_pct / 100);
        const savingResident = Math.round(annual * resident_tax_rate_pct / 100);
        const totalSaving = savingIncome + savingResident;
        const effectiveCost = annual - totalSaving;

        const result = { monthly_contribution: monthly, annual_contribution: annual, income_tax_rate_pct, resident_tax_rate_pct, tax_saving_income: savingIncome, tax_saving_resident: savingResident, total_tax_saving: totalSaving, effective_cost: effectiveCost, effective_monthly_cost: Math.round(effectiveCost / 12) };

        return {
          content: [{ type: "text", text: `💰 DC節税効果\n月額拠出: ${monthly.toLocaleString()}円 → 年間${annual.toLocaleString()}円\n所得税軽減: ${savingIncome.toLocaleString()}円\n住民税軽減: ${savingResident.toLocaleString()}円\n合計節税: ${totalSaving.toLocaleString()}円/年\n実質負担: 月${Math.round(effectiveCost / 12).toLocaleString()}円\n\n${JSON.stringify(result, null, 2)}` }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── calc_nisa_cap_usage ────────────────────────────────────
  server.registerTool(
    "calc_nisa_cap_usage",
    {
      title: "NISA枠使用状況シミュレーション",
      description: `月額積立でNISA生涯投資枠（1,800万円）の消化年数を試算します。

Use when: NISA枠消化のペース確認`,
      inputSchema: z.object({
        monthly_amount: z.number().int().min(1).describe("月額積立（円）"),
        already_used: z.number().int().min(0).optional().default(0).describe("既使用額（円）"),
        current_age: z.number().int().min(18).max(80).optional().default(27).describe("現在の年齢（デフォルト27）"),
        lifetime_cap: z.number().int().min(1).optional().default(18_000_000).describe("NISA生涯上限（円、デフォルト1800万）"),
        annual_cap: z.number().int().min(1).optional().default(1_200_000).describe("NISA年間上限（円、デフォルト120万）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ monthly_amount, already_used = 0, current_age = 27, lifetime_cap = 18_000_000, annual_cap = 1_200_000 }) => {
      try {
        const annual = monthly_amount * 12;
        const remaining = lifetime_cap - already_used;
        const yearsToFill = remaining / annual;
        const fillYear = new Date().getFullYear() + Math.ceil(yearsToFill);
        const fillAge = current_age + Math.ceil(yearsToFill);
        const exceedsAnnualCap = annual > annual_cap;

        const result = { monthly_amount, annual_amount: annual, lifetime_cap, annual_cap, already_used, remaining_cap: remaining, years_to_fill: +yearsToFill.toFixed(1), fill_year: fillYear, fill_age: fillAge, exceeds_annual_cap: exceedsAnnualCap, warning: exceedsAnnualCap ? `月額${monthly_amount.toLocaleString()}円（年${annual.toLocaleString()}円）はNISA年間上限${annual_cap.toLocaleString()}円を超えています` : null };

        return {
          content: [{ type: "text", text: `📋 NISA枠シミュレーション\n月額: ${monthly_amount.toLocaleString()}円（年${(annual / 10000).toFixed(0)}万円）\n生涯枠残余: ${(remaining / 10000).toFixed(0)}万円\n枠消化: 約${yearsToFill.toFixed(1)}年後（${fillYear}年・${fillAge}歳）${exceedsAnnualCap ? "\n⚠️ " + result.warning : ""}\n\n${JSON.stringify(result, null, 2)}` }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
