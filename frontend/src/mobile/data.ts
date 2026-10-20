import { getBudgetSummary } from '../api';
import type { MonthlyPlanLineType } from '../types';
import { loadAccounts, type DatabaseAccount } from '../studio/pages/db/forms';
import { buildModel, type BudgetModel, type BudgetSummary } from '../studio/pages/plan/budgetRows';

/** The month's plan as the studio's 計画 builds it, with the accounts it names. */
export async function loadMonth(period: string): Promise<{ summary: BudgetSummary; accounts: DatabaseAccount[]; model: BudgetModel }> {
    const [summary, accounts] = await Promise.all([getBudgetSummary(period, { include_unset: true }) as Promise<BudgetSummary>, loadAccounts()]);
    return { summary, accounts, model: buildModel(summary, accounts, []) };
}

/** Budget and actual of one movement across every account row. */
export function totals(model: BudgetModel, type: MonthlyPlanLineType): { budget: number; actual: number } {
    let budget = 0;
    let actual = 0;
    for (const row of model.accounts) {
        for (const cell of row.cells) {
            if (cell.type !== type) continue;
            budget += cell.budget;
            actual += cell.actual;
        }
    }
    return { budget, actual };
}

export const accountTypes = (accounts: DatabaseAccount[]) => new Map(accounts.map((account) => [account.id, account.account_type]));
