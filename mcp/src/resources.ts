// ============================================================
// MCP resources
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { api } from "./api-client.js";

function jsonText(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

const GUIDE_RESOURCES: Record<string, { title: string; description: string; text: string }> = {
  "asset-management://guide/overview": {
    title: "AssetManagement MCP guide overview",
    description: "High-level guidance for agents using AssetManagement MCP tools.",
    text: `# AssetManagement MCP Guide

Always treat journal entries as the source of truth. Account balances are changed by transactions, not by direct account edits.

Before write operations:
1. Read the relevant guide resource.
2. Prefer preview/validate tools before create/update tools.
3. Use exact account IDs from accounts_list.
4. If unsure about transaction type, call help_choose_transaction_type.

Important write tools:
- transactions_create / transactions_update: posts journal entries and changes balances.
- recurring_create: creates a definition only; no real transaction is posted until recurring_process.
- transaction_batches_create: posts multiple transactions at once.
- products_create / products_update: updates Product/Item registry and reserve planning metadata.
- data_import_replace_current_client and delete tools are destructive.`,
  },
  "asset-management://guide/accounting-rules": {
    title: "Accounting rules",
    description: "Transaction type, account side, and double-entry rules.",
    text: `# Accounting Rules

The UI/MCP payload uses from_account_id as the credit side and to_account_id as the debit side.

Transaction types:
- Income: from income, to asset. Example: salary account -> bank.
- Expense: from asset, to expense. Example: cash/bank -> food.
- Transfer: from asset, to asset. Example: bank -> savings.
- LiabilityPayment: from asset, to liability. Example: bank -> loan or credit card settlement.
- Borrowing: from liability, to asset. Example: loan -> bank.
- CreditExpense: from liability, to expense. Example: credit card -> food.
- CreditAssetPurchase: from liability, to asset. Use only for purchases that should be capitalized.

Common mistakes:
- Credit-card purchases are usually CreditExpense, not Expense.
- Credit-card repayment is LiabilityPayment, not Expense.
- Borrowed money is Borrowing, not Income.
- Ordinary household consumables paid by card are CreditExpense plus Product registration if needed.
- Never set Account.balance directly; create a transaction instead.`,
  },
  "asset-management://guide/data-entry": {
    title: "Data entry guide",
    description: "How agents should register transactions and products.",
    text: `# Data Entry Guide

For receipt or purchase-history entry:
1. Identify payment method.
2. Identify whether the item is a consumable, ordinary expense, or fixed asset.
3. Call help_choose_transaction_type if the type is not obvious.
4. Call validate_transaction_payload or transactions_preview.
5. Only then call transactions_create or transaction_batches_create.

Product/Item registry is separate from Transaction.
- Register both when the user asks to track product economics/reserve planning and record the payment.
- For consumables, set is_asset=false, frequency_days when known, last_purchase_date, budget_account_id when available.
- For fixed assets, set is_asset=true, purchase_price, purchase_date, and lifespan_months when known.
- Do not invent prices or account IDs. Ask or list accounts/products first.`,
  },
  "asset-management://guide/recurring": {
    title: "Recurring transaction guide",
    description: "Rules for recurring transaction definitions.",
    text: `# Recurring Transaction Guide

recurring_create creates a schedule definition only. It does not post a real transaction.

Use the same account-side rules as normal transactions:
- Expense: from asset, to expense.
- CreditExpense: from liability, to expense.
- Income: from income, to asset.
- LiabilityPayment: from asset, to liability.

Before recurring_create:
1. Call recurring_preview with the intended fields.
2. Confirm next_due_date, frequency, day_of_month, and account IDs.
3. Use recurring_process only when the due transaction should actually be posted.`,
  },
  "asset-management://guide/product-reserve": {
    title: "Product reserve guide",
    description: "Product/Item and reserve planning behavior.",
    text: `# Product Reserve Guide

Product budget treatment:
- auto + is_asset=true => asset_replacement.
- auto + consumable frequency_days <= 45 => expense_only.
- auto + consumable frequency_days > 45 or unknown => reserve_allocation.

Reserve-backed products should have funding_capsule_id when a specific reserve pool is known. The backend can assign defaults for product reserve pools in normal product flows.

Use products_preview before products_create when uncertain. The preview explains unit cost, monthly cost, effective treatment, and likely reserve behavior.`,
  },
  "asset-management://guide/dangerous-operations": {
    title: "Dangerous operations",
    description: "Operations that require extra confirmation.",
    text: `# Dangerous Operations

Treat these as high-risk:
- data_import_replace_current_client: replaces current client data.
- transactions_delete: reverts journal entries and changes balances.
- products_delete, accounts_delete, quick_templates_delete, exchange_rates_delete, simulation_scenarios_delete.
- recurring_process: posts a real transaction when due.
- actions_apply / actions_process_due / reports_apply_action: applies generated proposals.

For high-risk operations, explain the expected effect, call preview/list tools first, and require explicit user confirmation.`,
  },
};

export function registerResources(server: McpServer): void {
  for (const [uri, guide] of Object.entries(GUIDE_RESOURCES)) {
    server.registerResource(
      uri.replace("asset-management://guide/", "guide-"),
      uri,
      {
        title: guide.title,
        description: guide.description,
        mimeType: "text/markdown",
      },
      async (resourceUri) => ({
        contents: [{ uri: resourceUri.href, mimeType: "text/markdown", text: guide.text }],
      }),
    );
  }

  server.registerResource(
    "financial-summary",
    "asset-management://summary",
    {
      title: "Financial summary",
      description: "Current summary from /analysis/summary.",
      mimeType: "application/json",
    },
    async (uri) => {
      const data = await api.get<unknown>("/analysis/summary");
      return {
        contents: [{ uri: uri.href, mimeType: "application/json", text: jsonText(data) }],
      };
    },
  );

  server.registerResource(
    "recent-transactions",
    "asset-management://transactions/recent",
    {
      title: "Recent transactions",
      description: "Newest 10 transactions from /transactions/.",
      mimeType: "application/json",
    },
    async (uri) => {
      const data = await api.get<unknown>("/transactions/?limit=10");
      return {
        contents: [{ uri: uri.href, mimeType: "application/json", text: jsonText(data) }],
      };
    },
  );
}
