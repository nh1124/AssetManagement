import { z } from "zod";
import { api } from "./api-client.js";

export const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

export const transactionLegSchema = z
  .object({
    account_id: z.number().int().min(1).describe("Account this leg touches"),
    debit: z.number().min(0).optional().default(0).describe("Debit amount; exactly one of debit or credit is above zero"),
    credit: z.number().min(0).optional().default(0).describe("Credit amount"),
    memo: z.string().optional().describe("Note for this leg alone, e.g. \"own share\" or \"advance for A\""),
  })
  .strict();

export const transactionPayloadSchema = z
  .object({
    date: dateSchema.optional().describe("Transaction date, YYYY-MM-DD"),
    description: z.string().min(1).optional().describe("Description"),
    amount: z.number().min(0).describe("Amount; the whole payment"),
    from_account_id: z.number().int().min(1).optional().describe("Account the money leaves; this becomes the credit side"),
    to_account_id: z.number().int().min(1).optional().describe("Account the money reaches; this becomes the debit side"),
    currency: z.string().optional().default("JPY").describe("Currency"),
    legs: z
      .array(transactionLegSchema)
      .min(2)
      .optional()
      .describe(
        "Journal legs, for a payment that splits across more than two accounts. " +
          "Debits and credits must each total the amount. Omit for an ordinary two-sided entry, " +
          "where from_account_id is the credit side and to_account_id the debit side.",
      ),
  })
  .strict();

export interface Account {
  id: number;
  name: string;
  account_type: "asset" | "liability" | "income" | "expense" | string;
  role?: string | null;
  liability_kind?: string | null;
  balance?: number;
  is_active?: boolean;
}

/** What a pair of accounts means, in the terms the reports use.
 *
 *  There is no transaction type to choose any more: the accounts say what the
 *  entry is. This is here so a preview can describe the entry back in words. */
function describeMovement(from?: Account, to?: Account): string {
  const fromType = from?.account_type;
  const toType = to?.account_type;
  if (fromType === "income") return "Income: earnings arriving in an account you own.";
  if (toType === "expense") {
    return fromType === "liability"
      ? "Expense paid by a liability: the budget is consumed now, the cash moves when that account is settled."
      : "Expense paid from an account you own: the budget and the cash move together.";
  }
  if (toType === "liability") return "Paying down a liability.";
  if (fromType === "liability") return "Drawing on a liability: it grows and an account you own receives the value.";
  if (fromType === "asset" && toType === "asset") return "Moving value between accounts you own.";
  return "Movement between the two accounts given.";
}

export async function fetchAccounts(): Promise<Account[]> {
  return api.get<Account[]>("/accounts/?is_active=true");
}

function findAccount(accounts: Account[], id: number | undefined): Account | undefined {
  if (id === undefined) return undefined;
  return accounts.find((account) => account.id === id);
}

function accountRef(accounts: Account[], id: number | undefined) {
  const account = findAccount(accounts, id);
  return {
    provided_id: id ?? null,
    resolved: account
      ? {
          id: account.id,
          name: account.name,
          account_type: account.account_type,
          balance: account.balance ?? null,
        }
      : null,
  };
}

export function validateLegs(input: z.infer<typeof transactionPayloadSchema>, accounts: Account[]) {
  const errors: string[] = [];
  const warnings: string[] = [];
  const legs = input.legs ?? [];

  let totalDebit = 0;
  let totalCredit = 0;
  for (const leg of legs) {
    const debit = leg.debit ?? 0;
    const credit = leg.credit ?? 0;
    totalDebit += debit;
    totalCredit += credit;
    if ((debit > 0) === (credit > 0)) {
      errors.push(`Leg on account ${leg.account_id} must be either a debit or a credit, not both or neither.`);
    }
    if (!findAccount(accounts, leg.account_id)) {
      errors.push(`Leg account_id ${leg.account_id} was not found among active accounts.`);
    }
  }
  if (Math.abs(totalDebit - totalCredit) > 0.01) {
    errors.push(`Legs do not balance: debit ${totalDebit} vs credit ${totalCredit}.`);
  } else if (Math.abs(totalDebit - input.amount) > 0.01) {
    errors.push(`Legs total ${totalDebit} but amount is ${input.amount}. The amount is the whole payment.`);
  }
  if (input.from_account_id !== undefined || input.to_account_id !== undefined) {
    warnings.push("from_account_id and to_account_id are ignored when legs are given; the legs decide.");
  }

  return { ok: errors.length === 0, errors, warnings };
}

export function validateTransactionPayload(input: z.infer<typeof transactionPayloadSchema>, accounts: Account[]) {
  if (input.legs?.length) {
    return validateLegs(input, accounts);
  }
  const errors: string[] = [];
  const warnings: string[] = [];

  if (input.amount <= 0) {
    warnings.push("Amount is zero. This is accepted by schema but is usually not useful.");
  }

  const from = findAccount(accounts, input.from_account_id);
  const to = findAccount(accounts, input.to_account_id);

  // Both are required: there is no type left to infer a missing account from,
  // and inferring one is how entries used to land on an arbitrary account.
  if (input.from_account_id === undefined) {
    errors.push("from_account_id is required, or pass legs.");
  } else if (!from) {
    errors.push(`from_account_id ${input.from_account_id} was not found among active accounts.`);
  }
  if (input.to_account_id === undefined) {
    errors.push("to_account_id is required, or pass legs.");
  } else if (!to) {
    errors.push(`to_account_id ${input.to_account_id} was not found among active accounts.`);
  }
  if (input.from_account_id !== undefined && input.from_account_id === input.to_account_id) {
    errors.push("from_account_id and to_account_id are the same. A transaction must move value between two sides.");
  }
  if (from?.account_type === "expense") {
    errors.push(`from_account_id ${from.id} (${from.name}) is an expense account. An expense is the destination, not the source.`);
  }
  if (to?.account_type === "income") {
    errors.push(`to_account_id ${to.id} (${to.name}) is an income account. Income is the source, not the destination.`);
  }
  if (from?.account_type === "liability" && from.liability_kind !== "card" && to?.account_type === "expense") {
    warnings.push(
      `${from.name} is a liability that does not settle on a monthly cycle, so this expense will not appear in the card settlement projection. ` +
        "If it is a card, set its liability_kind; if it is a loan, the repayment belongs in the registry.",
    );
  }

  return { ok: errors.length === 0, errors, warnings };
}

export function previewTransactionPayload(input: z.infer<typeof transactionPayloadSchema>, accounts: Account[]) {
  const validation = validateTransactionPayload(input, accounts);

  if (input.legs?.length) {
    return {
      ok_to_submit: validation.ok,
      rule_summary: "Compound entry: the legs decide which accounts move.",
      amount: input.amount,
      currency: input.currency ?? "JPY",
      journal_preview: input.legs.map((leg) => {
        const account = findAccount(accounts, leg.account_id);
        const debit = leg.debit ?? 0;
        return {
          side: debit > 0 ? "debit" : "credit",
          account: account
            ? { id: account.id, name: account.name, account_type: account.account_type }
            : { id: leg.account_id },
          amount: debit > 0 ? debit : leg.credit ?? 0,
          memo: leg.memo ?? null,
        };
      }),
      validation,
      common_mistakes: [
        "Do not put the whole payment on every leg. Each leg carries its own share and the two sides must balance.",
        "Money fronted for someone else is a debit on a receivable asset account, not an expense leg.",
      ],
    };
  }

  const from = findAccount(accounts, input.from_account_id);
  const to = findAccount(accounts, input.to_account_id);
  const amount = input.amount;

  return {
    ok_to_submit: validation.ok,
    rule_summary: describeMovement(from, to),
    amount,
    currency: input.currency ?? "JPY",
    from_account: accountRef(accounts, input.from_account_id),
    to_account: accountRef(accounts, input.to_account_id),
    journal_preview: [
      { side: "debit", account: accountRef(accounts, input.to_account_id).resolved, amount },
      { side: "credit", account: accountRef(accounts, input.from_account_id).resolved, amount },
    ],
    balance_effect: {
      from_account: `credit ${amount}; an asset or expense account goes down, a liability or income account goes up`,
      to_account: `debit ${amount}; an asset or expense account goes up, a liability or income account goes down`,
    },
    validation,
    common_mistakes: [
      "from_account_id is where the money leaves, to_account_id where it arrives. An expense account is always a destination.",
      "Paying by card means from_account_id is the card, not a bank account.",
      "One payment split across several accounts is one entry with legs, not several transactions.",
    ],
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
