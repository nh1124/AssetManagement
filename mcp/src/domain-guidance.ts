import { z } from "zod";
import { api } from "./api-client.js";

export const transactionTypeSchema = z.enum([
  "Income",
  "Expense",
  "Transfer",
  "LiabilityPayment",
  "Borrowing",
  "CreditExpense",
  "CreditAssetPurchase",
]);

export const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

export const transactionPayloadSchema = z
  .object({
    date: dateSchema.optional().describe("Transaction date, YYYY-MM-DD"),
    description: z.string().min(1).optional().describe("Description"),
    amount: z.number().min(0).describe("Amount"),
    type: transactionTypeSchema.describe("Transaction type"),
    category: z.string().optional().describe("Category"),
    from_account_id: z.number().int().min(1).optional().describe("Source account ID; this becomes the credit side"),
    to_account_id: z.number().int().min(1).optional().describe("Destination account ID; this becomes the debit side"),
    currency: z.string().optional().default("JPY").describe("Currency"),
  })
  .strict();

export interface Account {
  id: number;
  name: string;
  account_type: "asset" | "liability" | "income" | "expense" | string;
  balance?: number;
  is_active?: boolean;
}

type AccountSide = "from" | "to";

interface TransactionRule {
  summary: string;
  fromType: Account["account_type"];
  toType: Account["account_type"];
  fromDefault: string;
  toDefault: string;
  fromLabel: string;
  toLabel: string;
  examples: string[];
  commonMistakes: string[];
}

export const TRANSACTION_RULES: Record<z.infer<typeof transactionTypeSchema>, TransactionRule> = {
  Income: {
    summary: "Income records money earned. The source is an income account; the destination is an asset account.",
    fromType: "income",
    toType: "asset",
    fromDefault: "salary or category",
    toDefault: "cash",
    fromLabel: "income/source account",
    toLabel: "receiving asset account",
    examples: ["salary paid into bank", "bonus received", "interest income credited to cash"],
    commonMistakes: ["Do not use an expense account as the source.", "Do not use Income for refunds unless they are treated as income."],
  },
  Expense: {
    summary: "Expense records cash/bank payment for an expense. The source is an asset account; the destination is an expense account.",
    fromType: "asset",
    toType: "expense",
    fromDefault: "cash",
    toDefault: "expense or category",
    fromLabel: "paying asset account",
    toLabel: "expense/category account",
    examples: ["cash lunch payment", "bank transfer for utilities", "debit card purchase"],
    commonMistakes: ["Do not use a credit card liability here; use CreditExpense.", "Do not put the expense category in from_account_id."],
  },
  Transfer: {
    summary: "Transfer moves money between asset accounts. Both sides are normally asset accounts.",
    fromType: "asset",
    toType: "asset",
    fromDefault: "cash",
    toDefault: "savings",
    fromLabel: "source asset account",
    toLabel: "destination asset account",
    examples: ["bank to savings", "cash to bank", "operating account to investment account"],
    commonMistakes: ["Do not use Transfer for expenses.", "Avoid using the same account on both sides."],
  },
  LiabilityPayment: {
    summary: "LiabilityPayment pays down debt. The source is an asset account; the destination is a liability account.",
    fromType: "asset",
    toType: "liability",
    fromDefault: "cash",
    toDefault: "loan",
    fromLabel: "paying asset account",
    toLabel: "liability being reduced",
    examples: ["loan repayment from bank", "credit card settlement from bank"],
    commonMistakes: ["Do not use Expense for principal repayment.", "Interest/fees may need a separate Expense transaction."],
  },
  Borrowing: {
    summary: "Borrowing records new debt proceeds. The source is a liability account; the destination is an asset account.",
    fromType: "liability",
    toType: "asset",
    fromDefault: "loan",
    toDefault: "cash",
    fromLabel: "liability account",
    toLabel: "asset account receiving proceeds",
    examples: ["loan drawdown into bank", "cash advance recorded as debt"],
    commonMistakes: ["Do not use Income for borrowed money.", "Do not use Borrowing for normal credit-card shopping."],
  },
  CreditExpense: {
    summary: "CreditExpense records a credit-card purchase consumed as an expense. The source is a liability account; the destination is an expense account.",
    fromType: "liability",
    toType: "expense",
    fromDefault: "credit",
    toDefault: "expense or category",
    fromLabel: "credit card/liability account",
    toLabel: "expense/category account",
    examples: ["Rakuten card grocery purchase", "card subscription fee", "Amazon consumable item paid by card"],
    commonMistakes: ["Do not use Expense when the payment method is credit card.", "Do not use the credit-card account as to_account_id."],
  },
  CreditAssetPurchase: {
    summary: "CreditAssetPurchase records buying an asset on credit. The source is a liability account; the destination is an asset account.",
    fromType: "liability",
    toType: "asset",
    fromDefault: "credit",
    toDefault: "savings",
    fromLabel: "credit card/liability account",
    toLabel: "asset account receiving the asset value",
    examples: ["equipment bought by credit card and capitalized", "fixed asset purchase on credit"],
    commonMistakes: ["Do not use this for ordinary consumables.", "For most household consumables paid by card, use CreditExpense plus Product if needed."],
  },
};

export async function fetchAccounts(): Promise<Account[]> {
  return api.get<Account[]>("/accounts/?is_active=true");
}

function findAccount(accounts: Account[], id: number | undefined): Account | undefined {
  if (id === undefined) return undefined;
  return accounts.find((account) => account.id === id);
}

function fallbackName(type: z.infer<typeof transactionTypeSchema>, side: AccountSide, category?: string): string {
  const rule = TRANSACTION_RULES[type];
  if (side === "from" && type === "Income" && category) return category;
  if (side === "to" && (type === "Expense" || type === "CreditExpense") && category) return category;
  return side === "from" ? rule.fromDefault : rule.toDefault;
}

function accountRef(accounts: Account[], id: number | undefined, type: z.infer<typeof transactionTypeSchema>, side: AccountSide, category?: string) {
  const rule = TRANSACTION_RULES[type];
  const account = findAccount(accounts, id);
  const expectedType = side === "from" ? rule.fromType : rule.toType;
  return {
    provided_id: id ?? null,
    resolved: account
      ? { id: account.id, name: account.name, account_type: account.account_type, balance: account.balance ?? null }
      : null,
    expected_account_type: expectedType,
    fallback_if_omitted: fallbackName(type, side, category),
  };
}

export function validateTransactionPayload(input: z.infer<typeof transactionPayloadSchema>, accounts: Account[]) {
  const rule = TRANSACTION_RULES[input.type];
  const errors: string[] = [];
  const warnings: string[] = [];

  if (input.amount <= 0) {
    warnings.push("Amount is zero. This is accepted by schema but is usually not useful.");
  }

  const from = findAccount(accounts, input.from_account_id);
  const to = findAccount(accounts, input.to_account_id);

  if (input.from_account_id !== undefined && !from) {
    errors.push(`from_account_id ${input.from_account_id} was not found among active accounts.`);
  }
  if (input.to_account_id !== undefined && !to) {
    errors.push(`to_account_id ${input.to_account_id} was not found among active accounts.`);
  }
  if (from && from.account_type !== rule.fromType) {
    errors.push(`from_account_id ${from.id} (${from.name}) is ${from.account_type}; ${input.type} expects ${rule.fromType}.`);
  }
  if (to && to.account_type !== rule.toType) {
    errors.push(`to_account_id ${to.id} (${to.name}) is ${to.account_type}; ${input.type} expects ${rule.toType}.`);
  }
  if (input.from_account_id !== undefined && input.from_account_id === input.to_account_id) {
    errors.push("from_account_id and to_account_id are the same. A transaction must move value between two sides.");
  }
  if ((input.type === "Expense" || input.type === "CreditExpense") && to && input.category && to.name !== input.category) {
    warnings.push(`Category "${input.category}" differs from destination expense account "${to.name}". Backend may preserve category, but reports often group by account.`);
  }
  if (input.type === "CreditAssetPurchase") {
    warnings.push("Use CreditAssetPurchase only when the purchase should be capitalized as an asset. Ordinary household consumables should usually be CreditExpense.");
  }

  return {
    ok: errors.length === 0,
    errors,
    warnings,
  };
}

export function previewTransactionPayload(input: z.infer<typeof transactionPayloadSchema>, accounts: Account[]) {
  const rule = TRANSACTION_RULES[input.type];
  const validation = validateTransactionPayload(input, accounts);
  const from = accountRef(accounts, input.from_account_id, input.type, "from", input.category);
  const to = accountRef(accounts, input.to_account_id, input.type, "to", input.category);
  const amount = input.amount;

  return {
    ok_to_submit: validation.ok,
    transaction_type: input.type,
    rule_summary: rule.summary,
    amount,
    currency: input.currency ?? "JPY",
    category: input.category ?? null,
    from_account: from,
    to_account: to,
    journal_preview: [
      {
        side: "debit",
        account: to.resolved ?? { fallback: to.fallback_if_omitted, expected_account_type: to.expected_account_type },
        amount,
      },
      {
        side: "credit",
        account: from.resolved ?? { fallback: from.fallback_if_omitted, expected_account_type: from.expected_account_type },
        amount,
      },
    ],
    balance_effect: {
      from_account: `credit ${amount}; for ${rule.fromType} accounts this ${rule.fromType === "asset" || rule.fromType === "expense" ? "decreases" : "increases"} balance`,
      to_account: `debit ${amount}; for ${rule.toType} accounts this ${rule.toType === "asset" || rule.toType === "expense" ? "increases" : "decreases"} balance`,
    },
    validation,
    common_mistakes: rule.commonMistakes,
  };
}

export function chooseTransactionType(params: {
  payment_method?: string;
  intent?: string;
  acquired_asset?: boolean;
  affects_liability?: boolean;
}) {
  const text = `${params.payment_method ?? ""} ${params.intent ?? ""}`.toLowerCase();
  const usesCredit = /credit|card|クレカ|カード|楽天カード|liability/.test(text);
  const isIncome = /income|salary|bonus|収入|給与|賞与|入金/.test(text);
  const isTransfer = /transfer|振替|移動|積替|savings|bank to bank/.test(text);
  const isBorrowing = /borrow|loan draw|借入|融資/.test(text);
  const isDebtPayment = /repay|payment|返済|支払.*ローン|カード.*引落/.test(text) || params.affects_liability;

  let recommended: z.infer<typeof transactionTypeSchema> = "Expense";
  if (isIncome) recommended = "Income";
  else if (isBorrowing) recommended = "Borrowing";
  else if (isDebtPayment && !usesCredit) recommended = "LiabilityPayment";
  else if (isTransfer) recommended = "Transfer";
  else if (usesCredit && params.acquired_asset) recommended = "CreditAssetPurchase";
  else if (usesCredit) recommended = "CreditExpense";
  else if (params.acquired_asset) recommended = "Expense";

  return {
    recommended_type: recommended,
    rule: TRANSACTION_RULES[recommended],
    alternatives: Object.entries(TRANSACTION_RULES).map(([type, rule]) => ({
      type,
      summary: rule.summary,
      examples: rule.examples,
    })),
  };
}

export function effectiveBudgetTreatment(product: {
  is_asset?: boolean;
  frequency_days?: number;
  budget_treatment?: string;
}) {
  if (product.budget_treatment && product.budget_treatment !== "auto") return product.budget_treatment;
  if (product.is_asset) return "asset_replacement";
  if (product.frequency_days !== undefined && product.frequency_days > 0 && product.frequency_days <= 45) return "expense_only";
  return "reserve_allocation";
}
