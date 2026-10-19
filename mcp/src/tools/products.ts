// ============================================================
// Product tools backed by FastAPI /products/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { effectiveBudgetTreatment, fetchAccounts } from "../domain-guidance.js";
import { toStructured } from "../utils.js";

const productInputSchema = z
  .object({
    name: z.string().min(1).describe("Product or item name"),
    category: z.string().optional().describe("Category name"),
    location: z.string().optional().describe("Store or location"),
    last_unit_price: z.number().min(0).describe("Latest purchase price"),
    units_per_purchase: z.number().int().min(1).optional().describe("Units per purchase"),
    frequency_days: z.number().int().min(0).optional().describe("Repurchase interval in days"),
    last_purchase_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Last purchase date, YYYY-MM-DD"),
    is_asset: z.boolean().optional().describe("True for fixed assets, false for consumables"),
    lifespan_months: z.number().int().min(1).optional().describe("Useful life in months for fixed assets"),
    budget_account_id: z.number().int().min(1).optional().describe("Expense account ID used as budget category"),
    funding_capsule_id: z.number().int().min(1).optional().describe("Reserve capsule ID"),
    budget_treatment: z
      .enum(["auto", "expense_only", "reserve_allocation", "asset_replacement"])
      .optional()
      .describe("How this product participates in budget/reserve planning"),
    auto_depreciation: z.boolean().optional(),
    depreciation_method: z.enum(["none", "straight_line", "declining_balance"]).optional(),
    depreciation_annual_rate: z.number().min(0).max(100).nullable().optional(),
    depreciation_interval: z.enum(["monthly", "yearly"]).optional(),
    depreciation_start_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).nullable().optional(),
    depreciation_expense_account_id: z.number().int().positive().nullable().optional(),
    depreciation_asset_account_id: z.number().int().positive().nullable().optional(),
    purchase_price: z.number().min(0).optional().describe("Original purchase price for fixed assets"),
    purchase_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Original purchase date, YYYY-MM-DD"),
  })
  .strict();

// A save that would change a linked earmark's target or monthly amount is refused
// (409 reserve_changes_unconfirmed) with the changes and a fingerprint.
const reserveFingerprint = z
  .string()
  .length(64)
  .optional()
  .describe("Fingerprint from a refused save. Pass it only after the user has seen and agreed to the listed earmark changes");
const RESERVE_CONFIRMATION =
  " If the save would change a linked earmark's target or monthly amount, it is refused with the changes and a fingerprint: show them to the user and repeat with reserve_fingerprint only after they agree.";

const productCreateSchema = productInputSchema.extend({ reserve_fingerprint: reserveFingerprint });

const productPatchSchema = productInputSchema.partial().extend({
  id: z.number().int().min(1).describe("Product ID"),
  reserve_fingerprint: reserveFingerprint,
});

type ProductInput = z.infer<typeof productInputSchema>;
type ProductCreate = z.infer<typeof productCreateSchema>;
type ProductPatch = z.infer<typeof productPatchSchema>;

function confirmation(fingerprint: string | undefined): string {
  return fingerprint ? `?reserve_fingerprint=${encodeURIComponent(fingerprint)}` : "";
}

const productPayloadKeys = [
  "name",
  "category",
  "location",
  "last_unit_price",
  "units_per_purchase",
  "frequency_days",
  "last_purchase_date",
  "is_asset",
  "lifespan_months",
  "budget_account_id",
  "funding_capsule_id",
  "budget_treatment",
  "purchase_price",
  "auto_depreciation", "depreciation_method", "depreciation_annual_rate", "depreciation_interval",
  "depreciation_start_date", "depreciation_expense_account_id", "depreciation_asset_account_id",
  "purchase_date",
] as const;

function productPayload(input: object): Record<string, unknown> {
  const source = input as Record<string, unknown>;
  const payload: Record<string, unknown> = {};
  for (const key of productPayloadKeys) {
    if (source[key] !== undefined) payload[key] = source[key];
  }
  return payload;
}

export function registerProductTools(server: McpServer): void {
  server.registerTool(
    "products_list",
    {
      title: "List products",
      description: "Returns products with unit economics fields, optionally filtered by category or asset flag.",
      inputSchema: z
        .object({
          category: z.string().optional().describe("Exact category filter"),
          is_asset: z.boolean().optional().describe("Filter by asset/consumable"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ category, is_asset }) => {
      try {
        const params = new URLSearchParams();
        if (category !== undefined) params.append("category", category);
        if (is_asset !== undefined) params.append("is_asset", String(is_asset));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/products/${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ products: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "products_create",
    {
      title: "Create product",
      description: "Creates a product or consumable item for the current client." + RESERVE_CONFIRMATION,
      inputSchema: productCreateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input: ProductCreate) => {
      try {
        const data = await api.post<unknown>(`/products/${confirmation(input.reserve_fingerprint)}`, productPayload(input));
        return {
          content: [{ type: "text", text: `Created product:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "products_preview",
    {
      title: "Preview product",
      description:
        "Previews Product/Item unit economics, reserve behavior, and account validation without saving it. Use before products_create.",
      inputSchema: productInputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input: ProductInput) => {
      try {
        const accounts = await fetchAccounts();
        const budgetAccount = input.budget_account_id
          ? accounts.find((account) => account.id === input.budget_account_id)
          : undefined;
        const errors: string[] = [];
        const warnings: string[] = [];
        if (input.budget_account_id && !budgetAccount) {
          errors.push(`budget_account_id ${input.budget_account_id} was not found among active accounts.`);
        }
        if (budgetAccount && budgetAccount.account_type !== "expense") {
          errors.push(`budget_account_id ${budgetAccount.id} (${budgetAccount.name}) is ${budgetAccount.account_type}; Product budget account must be expense.`);
        }
        if (input.is_asset && !input.lifespan_months) {
          warnings.push("Fixed assets should usually include lifespan_months for replacement reserve planning.");
        }
        if (!input.is_asset && (!input.frequency_days || input.frequency_days <= 0)) {
          warnings.push("Consumables should include frequency_days when monthly unit economics or reserve planning matters.");
        }

        const units = input.units_per_purchase || 1;
        const unitCost = input.last_unit_price / units;
        const monthlyCost = !input.is_asset && input.frequency_days && input.frequency_days > 0
          ? unitCost * (30 / input.frequency_days)
          : 0;
        const treatment = effectiveBudgetTreatment(input);
        const data = {
          ok_to_submit: errors.length === 0,
          product: input,
          unit_economics: {
            unit_cost: Math.round(unitCost * 100) / 100,
            monthly_cost: Math.round(monthlyCost * 100) / 100,
          },
          reserve_preview: {
            effective_budget_treatment: treatment,
            uses_reserve: treatment === "reserve_allocation" || treatment === "asset_replacement",
          },
          budget_account: budgetAccount
            ? { id: budgetAccount.id, name: budgetAccount.name, account_type: budgetAccount.account_type }
            : null,
          validation: { ok: errors.length === 0, errors, warnings },
        };
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
    "products_update",
    {
      title: "Update product",
      description: "Updates a product or consumable item. Missing fields are kept from the current product." + RESERVE_CONFIRMATION,
      inputSchema: productPatchSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ id, reserve_fingerprint, ...patch }: ProductPatch) => {
      try {
        const data = await api.patch<unknown>(`/products/${id}${confirmation(reserve_fingerprint)}`, productPayload(patch));
        return {
          content: [{ type: "text", text: `Updated product:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "products_delete",
    {
      title: "Delete product",
      description: "Deletes one product or consumable item." + RESERVE_CONFIRMATION,
      inputSchema: z
        .object({ id: z.number().int().min(1).describe("Product ID"), reserve_fingerprint: reserveFingerprint })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id, reserve_fingerprint }) => {
      try {
        const data = await api.delete<unknown>(`/products/${id}${confirmation(reserve_fingerprint)}`);
        return {
          content: [{ type: "text", text: `Deleted product ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data ?? { id, deleted: true }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "products_unit_economics_summary",
    {
      title: "Get unit economics summary",
      description: "Returns monthly consumable cost estimates by item and category.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/products/unit-economics-summary");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
