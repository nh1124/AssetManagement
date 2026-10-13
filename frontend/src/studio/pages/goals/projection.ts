import type { LifeEvent, Milestone, MonteCarloResult } from '../../../types';

export interface ProjectionRow {
    date: number;
    projection?: number;
    p10?: number;
    p50?: number;
    p90?: number;
    band?: [number, number];
    plan?: number;
}

const timestamp = (date: string) => Date.parse(`${date}T00:00:00Z`);

function interpolate(points: Array<{ date: number; amount: number }>, date: number): number {
    const next = points.findIndex((point) => point.date >= date);
    if (next === -1) return points.at(-1)?.amount ?? 0;
    if (next === 0) return points[0].amount;
    const start = points[next - 1];
    const end = points[next];
    return start.amount + (end.amount - start.amount) * (date - start.date) / (end.date - start.date);
}

export function projectionRows(goal: LifeEvent, milestones: Milestone[], referenceDate: string, mc: MonteCarloResult | null): ProjectionRow[] {
    const start = timestamp(referenceDate);
    const target = Math.max(start, timestamp(goal.target_date));
    const active = milestones.filter((row) => row.life_event_id === goal.id && row.is_active_plan !== false).sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);
    const plan = [{ date: start, amount: goal.plan_expected_amount ?? 0 }, ...active.filter((row) => timestamp(row.date) > start).map((row) => ({ date: timestamp(row.date), amount: row.target_amount }))];
    const dates = new Set([start, target, ...active.map((row) => timestamp(row.date)).filter((date) => date >= start && date <= target)]);
    const regular = [{ date: start, amount: goal.current_funded ?? 0 }];
    if (!mc) {
        // Monthly balances are whole periods from the reference day, even when labels omit it.
        for (const row of goal.roadmap ?? []) {
            if (!row.year) continue;
            const period = new Date(start);
            const day = period.getUTCDate();
            period.setUTCDate(1);
            period.setUTCMonth(period.getUTCMonth() + row.year);
            const lastDay = new Date(Date.UTC(period.getUTCFullYear(), period.getUTCMonth() + 1, 0)).getUTCDate();
            period.setUTCDate(Math.min(day, lastDay));
            const date = period.getTime();
            if (date > start && date < target) regular.push({ date, amount: row.end_balance });
        }
        // The progress response evaluates the fractional horizon, unlike the rounded period table.
        if (target > start) regular.push({ date: target, amount: goal.projected_amount ?? regular.at(-1)?.amount ?? 0 });
        regular.forEach((row) => dates.add(row.date));
    }
    const quantiles = (['p10', 'p50', 'p90'] as const).map((key) => {
        const values = mc?.year_by_year[key] ?? [];
        if (!values.length) return [{ date: start, amount: mc?.percentiles[key] ?? goal.current_funded ?? 0 }];
        return values.map((amount, index) => {
            // The final Monte Carlo sample is the partial year ending on the target date.
            const anniversary = new Date(start);
            const month = anniversary.getUTCMonth();
            anniversary.setUTCFullYear(anniversary.getUTCFullYear() + index);
            if (anniversary.getUTCMonth() !== month) anniversary.setUTCDate(0);
            const date = index === values.length - 1 ? target : Math.min(target, anniversary.getTime());
            dates.add(date);
            return { date, amount };
        });
    });
    return [...dates].sort((a, b) => a - b).map((date) => {
        const row: ProjectionRow = { date };
        if (active.length) row.plan = interpolate(plan, date);
        if (mc) {
            row.p10 = interpolate(quantiles[0], date);
            row.p50 = interpolate(quantiles[1], date);
            row.p90 = interpolate(quantiles[2], date);
            row.band = [row.p10, row.p90];
        } else row.projection = interpolate(regular, date);
        return row;
    });
}
