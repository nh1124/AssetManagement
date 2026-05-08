// ============================================================
// Product tools backed by FastAPI /products/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const productInputSchema = z
  .object({
    name: z.string().min(1).describe("Product or item name"),
    category: z.string().optional().default("Uncategorized").describe("Category name"),
    location: z.string().optional().describe("Store or location"),
    last_unit_price: z.number().min(0).describe("Latest purchase price"),
    units_per_purchase: z.number().int().min(1).optional().default(1).describe("Units per purchase"),
    frequency_days: z.number().int().min(0).optional().default(0).describe("Repurchase interval in days"),
    last_purchase_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Last purchase date, YYYY-MM-DD"),
    is_asset: z.boolean().optional().default(false).describe("True for fixed assets, false for consumables"),
    lifespan_months: z.number().int().min(1).optional().describe("Useful life in months for fixed assets"),
    budget_account_id: z.number().int().min(1).optional().describe("Expense account ID used as budget category"),
    funding_capsule_id: z.number().int().min(1).optional().describe("Reserve capsule ID"),
    budget_treatment: z
      .enum(["auto", "expense_only", "reserve_allocation", "asset_replacement"])
      .optional()
      .default("auto")
      .describe("How this product participates in budget/reserve planning"),
    purchase_price: z.number().min(0).optional().describe("Original purchase price for fixed assets"),
    purchase_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Original purchase date, YYYY-MM-DD"),
  })
  .strict();

const productPatchSchema = productInputSchema.partial().extend({
  id: z.number().int().min(1).describe("Product ID"),
});

type ProductInput = z.infer<typeof productInputSchema>;
type ProductPatch = z.infer<typeof productPatchSchema>;

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
      description: "Creates a product or consumable item for the current client.",
      inputSchema: productInputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input: ProductInput) => {
      try {
        const data = await api.post<unknown>("/products/", input);
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
    "products_update",
    {
      title: "Update product",
      description: "Updates a product or consumable item. Missing fields are kept from the current product.",
      inputSchema: productPatchSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ id, ...patch }: ProductPatch) => {
      try {
        const products = await api.get<Array<Record<string, unknown>>>("/products/");
        const current = products.find((product) => product.id === id);
        if (!current) {
          return { content: [{ type: "text", text: `Error: Product ${id} not found` }] };
        }

        const body = {
          name: current.name,
          category: current.category ?? "Uncategorized",
          location: current.location ?? undefined,
          last_unit_price: current.last_unit_price,
          units_per_purchase: current.units_per_purchase ?? 1,
          frequency_days: current.frequency_days ?? 0,
          last_purchase_date: current.last_purchase_date ?? undefined,
          is_asset: current.is_asset ?? false,
          lifespan_months: current.lifespan_months ?? undefined,
          budget_account_id: current.budget_account_id ?? undefined,
          funding_capsule_id: current.funding_capsule_id ?? undefined,
          budget_treatment: current.budget_treatment ?? "auto",
          purchase_price: current.purchase_price ?? undefined,
          purchase_date: current.purchase_date ?? undefined,
          ...patch,
        };
        const data = await api.put<unknown>(`/products/${id}`, body);
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
      description: "Deletes one product or consumable item.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Product ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/products/${id}`);
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
