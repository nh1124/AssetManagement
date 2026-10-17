import { useCallback, useEffect, useState } from 'react';
import { Flag } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { LifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import ScenarioComparison from './ScenarioComparison';
import { scenarioSelection } from './scenarioSimulation';
import { useMakeScenarioGoal } from './useMakeScenarioGoal';

function ComparisonPlot({ ids, scenarios, focusedId, currency, busy, onMakeGoal }: {
    ids: string; scenarios: LifeScenario[]; focusedId?: number; currency: string; busy: boolean; onMakeGoal: (id: number) => void;
}) {
    const load = useCallback(() => scenariosApi.compare(ids.split(',').map(Number)), [ids]);
    const resource = useResource(load);
    return <>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && !resource.error && <div className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <ScenarioComparison scenarios={resource.data.scenarios.map((row) => ({ ...row, is_goal: scenarios.find((scenario) => scenario.id === row.id)?.is_goal ?? false }))} focusedId={focusedId} currency={currency} colourIds={scenarios.map((row) => row.id)} onMakeGoal={onMakeGoal} busy={busy || resource.loading} />
        </div>}
    </>;
}

function ComparisonResults({ scenarios, currency, disabled, onChanged }: { scenarios: LifeScenario[]; currency: string; disabled: boolean; onChanged: () => void }) {
    const [search, setSearch] = useSearchParams();
    const { ids, focusedId } = scenarioSelection(scenarios, search);
    const checkedKey = ids.join(',');
    const [revision, setRevision] = useState(0);
    const goal = useMakeScenarioGoal(() => { onChanged(); setRevision((value) => value + 1); });
    const sorted = [...scenarios].sort((a, b) => Number(b.is_goal) - Number(a.is_goal) || a.id - b.id);
    useEffect(() => {
        const next = new URLSearchParams(search);
        next.set('ids', checkedKey);
        if (focusedId === undefined) next.delete('focus');
        else next.set('focus', String(focusedId));
        // Persist defaults so changing the goal cannot change the selected comparison.
        if (next.toString() !== search.toString()) setSearch(next, { replace: true });
    }, [checkedKey, focusedId, search, setSearch]);
    const choose = (nextIds: number[], nextFocus: number | undefined) => {
        const next = new URLSearchParams(search);
        next.set('ids', nextIds.join(','));
        if (nextFocus === undefined) next.delete('focus');
        else next.set('focus', String(nextFocus));
        setSearch(next);
    };
    return <>
        <div role="group" aria-label="比較するシナリオ" className="flex flex-wrap gap-2">
            {sorted.map((scenario) => <div key={`scenario-choice-${scenario.id}`} className={`flex items-center gap-2 rounded-lg border border-[var(--studio-border)] px-3 py-2 ${focusedId === scenario.id ? 'bg-[var(--studio-accent-soft)] ring-1 ring-[var(--studio-accent)]' : ''}`}>
                <input type="checkbox" aria-label={`${scenario.name}を比較する`} checked={ids.includes(scenario.id)} disabled={goal.busy} onChange={(event) => {
                    const next = event.target.checked ? [...ids, scenario.id] : ids.filter((id) => id !== scenario.id);
                    choose(next, next.includes(focusedId ?? -1) ? focusedId : next[0]);
                }} className="accent-[var(--studio-accent)]" />
                <button type="button" aria-pressed={focusedId === scenario.id} disabled={goal.busy} onClick={() => choose(ids.includes(scenario.id) ? ids : [...ids, scenario.id], scenario.id)} className="flex items-center gap-1.5 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">
                    {scenario.is_goal && <Flag size={14} aria-label="ゴール" />}{scenario.name}
                </button>
            </div>)}
        </div>
        <Feedback error={goal.error} />
        {ids.length === 0 ? <p className="text-sm text-[var(--studio-text-muted)]">比較するシナリオを選んでください。</p>
            // Remount on selection so stale projections and errors cannot describe a new set.
            : <ComparisonPlot key={`${checkedKey}:${revision}`} ids={checkedKey} scenarios={scenarios} focusedId={focusedId} currency={currency} busy={disabled || goal.busy} onMakeGoal={goal.chooseGoal} />}
    </>;
}

function ComparisonForClient({ currency, identified }: { currency: string; identified: boolean }) {
    const load = useCallback(() => scenariosApi.list(), []);
    const resource = useResource(load);
    return <section className="space-y-5">
        <Link to="/goals/scenarios" className={`inline-block ${buttonClass}`}>シナリオ一覧に戻る</Link>
        <h2 className="font-semibold">比較</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && !resource.error && <ComparisonResults scenarios={resource.data} currency={currency} disabled={!identified || resource.loading} onChanged={resource.reload} />}
    </section>;
}

export default function Comparison() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <ComparisonForClient key={`${clientId}:${currency}`} currency={currency} identified={currentClient?.id === clientId} />;
}
