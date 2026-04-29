// ============================================================
// Portfolio Management Tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { getPortfolio, savePortfolio } from "../store.js";
import { toStructured } from "../utils.js";

export function registerPortfolioTools(server: McpServer): void {

  // ── portfolio_get ──────────────────────────────────────────
  server.registerTool(
    "portfolio_get",
    {
      title: "ポートフォリオ取得",
      description: `現在の全投資設定（NISA・DC・持株会・緊急予備費）を取得します。

Returns:
  - profile: プロフィール（名前・年齢・手取り）
  - investments.nisa: 積立NISAの設定
  - investments.dc: 企業型DCマッチング拠出の設定
  - investments.holdings: NTT持株会の設定
  - emergency_fund: 緊急予備費の積立状況
  - summary: 月次投資合計・米国株比率など

Use when: 投資設定全体を確認したいとき / 設定変更前後の確認`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const portfolio = getPortfolio();
        return {
          content: [{ type: "text", text: JSON.stringify(portfolio, null, 2) }],
          structuredContent: toStructured(portfolio)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── portfolio_update ───────────────────────────────────────
  server.registerTool(
    "portfolio_update",
    {
      title: "投資設定を更新",
      description: `NISA・DC・持株会のいずれかの投資設定を更新します。

Args:
  - account (string): 更新対象アカウント。"nisa" | "dc" | "holdings"
  - monthly_amount (number, optional): 月額積立金額（円）
  - fund (string, optional): 投資ファンド名
  - expense_ratio (number, optional): 信託報酬（%、例: 0.05775）
  - notes (string, optional): メモ・備考

Returns: 更新後のポートフォリオ全体

Use when: 積立額変更・ファンド変更・メモ更新`,
      inputSchema: z.object({
        account: z.enum(["nisa", "dc", "holdings"])
          .describe("更新対象: 'nisa' | 'dc' | 'holdings'"),
        monthly_amount: z.number().int().min(0).optional()
          .describe("月額積立金額（円）"),
        fund: z.string().min(1).optional()
          .describe("投資ファンド名"),
        expense_ratio: z.number().min(0).max(5).optional()
          .describe("信託報酬（年率%）"),
        notes: z.string().optional()
          .describe("メモ・備考")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ account, monthly_amount, fund, expense_ratio, notes }) => {
      try {
        const portfolio = getPortfolio();
        const inv = portfolio.investments[account];

        if (monthly_amount !== undefined) inv.monthly_amount = monthly_amount;
        if (fund !== undefined) inv.fund = fund;
        if (expense_ratio !== undefined) inv.expense_ratio = expense_ratio;
        if (notes !== undefined) inv.notes = notes;

        if (account === "holdings" && monthly_amount !== undefined && inv.bonus_rate !== undefined) {
          inv.effective_monthly = Math.round(monthly_amount * (1 + inv.bonus_rate / 100));
        }

        const nisa = portfolio.investments.nisa.monthly_amount;
        const dc = portfolio.investments.dc.monthly_amount;
        const hold = portfolio.investments.holdings.monthly_amount;
        const emergency = portfolio.emergency_fund.monthly_contribution;
        portfolio.summary.total_monthly_investment = nisa + dc + hold;
        portfolio.summary.total_monthly_allocation = nisa + dc + hold + emergency;

        savePortfolio(portfolio);
        return {
          content: [{ type: "text", text: `✅ ${account} を更新しました。\n\n${JSON.stringify(portfolio, null, 2)}` }],
          structuredContent: toStructured(portfolio)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── portfolio_update_emergency_fund ───────────────────────
  server.registerTool(
    "portfolio_update_emergency_fund",
    {
      title: "緊急予備費を更新",
      description: `緊急予備費の現在残高・目標額・月次積立額を更新します。

Args:
  - current (number, optional): 現在の残高（円）
  - target (number, optional): 目標額（円、デフォルト270,000円）
  - monthly_contribution (number, optional): 月次積立額（円）
  - account (string, optional): 預け入れ先口座名

Returns: 更新後のポートフォリオ全体 + 達成率`,
      inputSchema: z.object({
        current: z.number().int().min(0).optional().describe("現在の残高（円）"),
        target: z.number().int().min(0).optional().describe("目標額（円）"),
        monthly_contribution: z.number().int().min(0).optional().describe("月次積立額（円）"),
        account: z.string().optional().describe("預け入れ先口座名")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ current, target, monthly_contribution, account }) => {
      try {
        const portfolio = getPortfolio();
        const ef = portfolio.emergency_fund;

        if (current !== undefined) ef.current = current;
        if (target !== undefined) ef.target = target;
        if (monthly_contribution !== undefined) ef.monthly_contribution = monthly_contribution;
        if (account !== undefined) ef.account = account;

        const progress_pct = ef.target > 0 ? Math.round((ef.current / ef.target) * 100) : 0;
        const remaining = ef.target - ef.current;
        const months_to_goal = monthly_contribution !== undefined && monthly_contribution > 0
          ? Math.ceil(remaining / monthly_contribution)
          : (ef.monthly_contribution > 0 ? Math.ceil(remaining / ef.monthly_contribution) : null);

        savePortfolio(portfolio);

        const summary = { updated: portfolio.emergency_fund, progress_pct, remaining_amount: remaining, estimated_months_to_goal: months_to_goal };
        return {
          content: [{ type: "text", text: `✅ 緊急予備費を更新しました。\n達成率: ${progress_pct}%\n残り: ${remaining.toLocaleString()}円\n目標到達まで: ${months_to_goal ?? "?"}ヶ月\n\n${JSON.stringify(summary, null, 2)}` }],
          structuredContent: toStructured(summary)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── portfolio_summary ──────────────────────────────────────
  server.registerTool(
    "portfolio_summary",
    {
      title: "ポートフォリオサマリー",
      description: `月次投資合計・資産配分・米国株比率などの概要サマリーを返します。

Returns:
  - monthly_totals: 各投資先の月額と合計
  - cashflow: 手取り・投資後の残額
  - allocation: 各投資先の割合（%）
  - us_equity_ratio: 合算の米国株比率（%）
  - emergency_fund_progress: 緊急予備費の達成率

Use when: 投資配分の概要確認・バランスチェック`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const p = getPortfolio();
        const { nisa, dc, holdings } = p.investments;
        const ef = p.emergency_fund;

        const total_invest = nisa.monthly_amount + dc.monthly_amount + holdings.monthly_amount;
        const total_alloc = total_invest + ef.monthly_contribution;
        const remainder = p.profile.take_home - total_alloc;

        const summary = {
          as_of: p.as_of,
          profile: { name: p.profile.name, age: p.profile.age, take_home: p.profile.take_home },
          monthly_totals: {
            nisa: nisa.monthly_amount, dc: dc.monthly_amount, holdings: holdings.monthly_amount,
            emergency_fund: ef.monthly_contribution, total_investment: total_invest,
            total_allocated: total_alloc, remainder
          },
          allocation_pct: {
            nisa: +(nisa.monthly_amount / total_invest * 100).toFixed(1),
            dc: +(dc.monthly_amount / total_invest * 100).toFixed(1),
            holdings: +(holdings.monthly_amount / total_invest * 100).toFixed(1)
          },
          us_equity_ratio_pct: p.summary.us_equity_ratio,
          emergency_fund: {
            current: ef.current, target: ef.target,
            progress_pct: ef.target > 0 ? Math.round(ef.current / ef.target * 100) : 0
          },
          funds: {
            nisa: `${nisa.fund ?? "未設定"} (信託報酬: ${nisa.expense_ratio ?? "?"}%)`,
            dc: `${dc.fund ?? "未設定"} (信託報酬: ${dc.expense_ratio ?? "?"}%)`
          }
        };

        return {
          content: [{ type: "text", text: JSON.stringify(summary, null, 2) }],
          structuredContent: toStructured(summary)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
