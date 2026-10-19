import type { Product } from '../../../types';

type Treatment = NonNullable<Product['budget_treatment']>;

export function effectiveProductTreatment(treatment: Treatment, assets: boolean, cycleDays: number): Exclude<Treatment, 'auto'> {
    if (treatment !== 'auto') return treatment;
    if (assets) return 'asset_replacement';
    return cycleDays > 0 && cycleDays <= 45 ? 'expense_only' : 'reserve_allocation';
}
