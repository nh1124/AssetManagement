import type { LifeScenario, ProjectedLifeScenario } from '../../../api/lifeScenarios';

export function scenarioSelection(scenarios: LifeScenario[], search: URLSearchParams) {
    const sorted = [...scenarios].sort((a, b) => Number(b.is_goal) - Number(a.is_goal) || a.id - b.id);
    const valid = new Set(sorted.map((scenario) => scenario.id));
    const requested = search.has('ids') ? (search.get('ids') ?? '').split(',').map(Number).filter((id) => valid.has(id)) : sorted.slice(0, 3).map((scenario) => scenario.id);
    const ids = [...new Set(requested)];
    const requestedFocus = Number(search.get('focus'));
    const focusedId = ids.includes(requestedFocus) ? requestedFocus : ids[0];
    return { ids, focusedId };
}

export function lowestProbability(scenario: ProjectedLifeScenario): number | null {
    const probabilities = scenario.conditions.filter((event) => event.conditions.length > 0)
        .map((event) => event.probability).filter((value) => value !== null);
    return probabilities.length ? Math.min(...probabilities) : null;
}
