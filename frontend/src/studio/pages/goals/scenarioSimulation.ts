import * as api from '../../../api/lifeScenarios';
import type { LifeScenario, LifeScenarioAccountReturn, ProjectedLifeScenario } from '../../../api/lifeScenarios';

export type Parameters = Pick<LifeScenario, 'horizon_years' | 'annual_return' | 'inflation'>;
export type ParameterDraft = Record<keyof Parameters, string>;
export type ReturnDraft = Record<number, string>;
type Pending = { parameters?: Parameters; returns?: LifeScenarioAccountReturn[] };

export function parseParameters(draft: ParameterDraft): Parameters | null {
    if (Object.values(draft).some((value) => !value.trim())) return null;
    const horizon_years = Number(draft.horizon_years);
    const annual_return = Number(draft.annual_return);
    const inflation = Number(draft.inflation);
    if (!Number.isInteger(horizon_years) || horizon_years < 1 || horizon_years > 60 || !Number.isFinite(annual_return) || !Number.isFinite(inflation)) return null;
    return { horizon_years, annual_return, inflation };
}

export function parseReturns(draft: ReturnDraft): LifeScenarioAccountReturn[] | null {
    const rows: LifeScenarioAccountReturn[] = [];
    for (const [id, value] of Object.entries(draft)) {
        // Empty removes an override, preserving the account's own return as fallback.
        if (!value.trim()) continue;
        if (!Number.isFinite(Number(value))) return null;
        rows.push({ account_id: Number(id), annual_return: Number(value) });
    }
    return rows;
}

export function scenarioSelection(scenarios: LifeScenario[], search: URLSearchParams) {
    const sorted = [...scenarios].sort((a, b) => Number(b.is_goal) - Number(a.is_goal) || a.id - b.id);
    const valid = new Set(sorted.map((scenario) => scenario.id));
    const requested = search.has('ids') ? (search.get('ids') ?? '').split(',').map(Number).filter((id) => valid.has(id)) : sorted.slice(0, 3).map((scenario) => scenario.id);
    const ids = [...new Set(requested)];
    const requestedFocus = Number(search.get('focus'));
    const focusedId = ids.includes(requestedFocus) ? requestedFocus : ids[0];
    return { ids, focusedId };
}

export class ScenarioSaveQueue {
    private pending = new Map<number, Pending>();
    private queue: Promise<unknown> = Promise.resolve();

    stage(id: number, values: Pending) {
        this.pending.set(id, { ...this.pending.get(id), ...values });
    }

    run<T>(action: () => Promise<T>): Promise<T> {
        const result = this.queue.then(action);
        // One failed request must not prevent later edits or the departure flush.
        this.queue = result.catch(() => {});
        return result;
    }

    flush(): Promise<boolean> {
        const snapshot = [...this.pending];
        return this.run(async () => {
            let saved = false;
            const failures: unknown[] = [];
            for (const [id, values] of snapshot) {
                const parameters = values.parameters;
                const returns = values.returns;
                if (parameters && this.pending.get(id)?.parameters === parameters) {
                    try {
                        await api.update(id, parameters);
                        if (this.pending.get(id)?.parameters === parameters) delete this.pending.get(id)?.parameters;
                        saved = true;
                    } catch (failure: unknown) { failures.push(failure); }
                }
                if (returns && this.pending.get(id)?.returns === returns) {
                    try {
                        await api.setAccountReturns(id, returns);
                        if (this.pending.get(id)?.returns === returns) delete this.pending.get(id)?.returns;
                        saved = true;
                    } catch (failure: unknown) { failures.push(failure); }
                }
            }
            if (failures.length) throw failures[0];
            return saved;
        });
    }
}

export function lowestProbability(scenario: ProjectedLifeScenario): number | null {
    const probabilities = scenario.conditions.filter((event) => event.conditions.length > 0)
        .map((event) => event.probability).filter((value) => value !== null);
    return probabilities.length ? Math.min(...probabilities) : null;
}
