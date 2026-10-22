import { Target } from 'lucide-react';
import type { ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import { DataTable } from '../db/Database';
import { buttonClass } from '../db/forms';
import { lowestProbability } from './scenarioSimulation';
import ScenarioProjectionChart from './ScenarioProjectionChart';
import { tr } from '../../i18n';

function EventTotal({ scenario, direction, currency }: { scenario: ProjectedLifeScenario; direction: 'expense' | 'income'; currency: string }) {
    const totals = new Map<string, number>();
    for (const event of scenario.events) if (event.direction === direction) totals.set(event.currency, (totals.get(event.currency) ?? 0) + event.target_amount);
    return totals.size ? [...totals].map(([code, amount]) => <span key={code} className="block whitespace-nowrap">{formatCurrency(amount, code)}{tr(`（${code}）`, ` (${code})`)}</span>) : formatCurrency(0, currency);
}

export default function ScenarioComparison({ scenarios, focusedId, currency, colourIds, onMakeGoal, busy = false }: { scenarios: ProjectedLifeScenario[]; focusedId?: number; currency: string; colourIds: number[]; onMakeGoal?: (scenario: ProjectedLifeScenario) => void; busy?: boolean }) {
    return <>
        <ScenarioProjectionChart scenarios={scenarios} focusedId={focusedId} currency={currency} colourIds={colourIds} />
        <DataTable columns={[tr('シナリオ', 'Scenario'), tr('最終純資産（中央値）', 'Final net worth (median)'), tr('支出合計', 'Total spending'), tr('収入合計', 'Total income'), tr('前提条件', 'Preconditions'), ...(onMakeGoal ? [''] : [])]}>
            {scenarios.map((scenario) => {
                const lowest = lowestProbability(scenario);
                return <tr key={`scenario-row-${scenario.id}`} className={scenario.id === focusedId ? 'bg-[var(--studio-accent-soft)]' : ''}>
                    <th scope="row" className="px-5 py-3 font-medium"><span className="inline-flex items-center gap-2">{scenario.is_goal && <Target size={14} aria-label={tr('ゴール', 'Goal')} />}{scenario.name}</span></th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{scenario.projection.length ? formatCurrency(scenario.projection.at(-1)?.p50, currency) : '—'}</td>
                    <td className="px-5 py-3 tabular-nums"><EventTotal scenario={scenario} direction="expense" currency={currency} /></td>
                    <td className="px-5 py-3 tabular-nums"><EventTotal scenario={scenario} direction="income" currency={currency} /></td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{lowest === null ? '—' : `${Math.round(lowest * 100)}%`}</td>
                    {onMakeGoal && <td className="whitespace-nowrap px-5 py-3">{!scenario.is_goal && <button type="button" disabled={busy} onClick={() => onMakeGoal(scenario)} className={buttonClass}>{tr('ゴールにする', 'Make it the goal')}</button>}</td>}
                </tr>;
            })}
        </DataTable>
    </>;
}
