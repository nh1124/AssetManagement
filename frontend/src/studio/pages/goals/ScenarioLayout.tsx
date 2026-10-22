import { useCallback } from 'react';
import { Target } from 'lucide-react';
import { Link, Outlet, useLocation, useParams } from 'react-router-dom';
import { list } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass, primaryClass } from '../db/forms';
import { tr } from '../../i18n';

const steps = [
    { segment: 'events', get label() { return tr('ライフイベント', 'Life events'); } },
    { segment: 'graph', get label() { return tr('構成', 'Structure'); } },
    { segment: 'simulation', get label() { return tr('シミュレーション', 'Simulation'); } },
] as const;

function ScenarioForClient({ scenarioId }: { scenarioId: string }) {
    const { pathname } = useLocation();
    const load = useCallback(async () => {
        const scenario = (await list()).find((row) => row.id === Number(scenarioId));
        if (!scenario) throw new Error(tr('このシナリオは見つかりません。', 'This scenario was not found.'));
        return scenario;
    }, [scenarioId]);
    const resource = useResource(load);
    const base = `/goals/scenarios/${scenarioId}`;
    const current = steps.findIndex((step) => pathname === `${base}/${step.segment}` || pathname.startsWith(`${base}/${step.segment}/`));
    const next = steps[current + 1];
    return <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-4">
            <Link to="/goals/scenarios" className={buttonClass}>{tr('シナリオ一覧に戻る', 'Back to scenarios')}</Link>
            {resource.data && <h2 className="flex items-center gap-2 font-semibold">{resource.data.is_goal && <Target size={18} aria-label={tr('ゴール', 'Goal')} />}{resource.data.name}</h2>}
        </div>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && !resource.loading && !resource.error && <>
            <nav aria-label={tr('シナリオの編集手順', 'Scenario steps')}>
                <ol className="grid gap-2 sm:grid-cols-3">
                    {steps.map((step, index) => <li key={`step-${step.segment}`}>
                        <Link to={`${base}/${step.segment}`} aria-current={index === current ? 'step' : undefined}
                            className={`flex items-center gap-2 rounded-lg border p-3 text-sm ${index === current ? 'border-[var(--studio-accent)] bg-[var(--studio-accent-soft)] font-semibold text-[var(--studio-accent)]' : 'border-[var(--studio-border)] text-[var(--studio-text-muted)] hover:bg-[var(--studio-surface)]'}`}>
                            <span>{index + 1}</span>{step.label}
                        </Link>
                    </li>)}
                </ol>
            </nav>
            {/* Each step edits only this scenario's story. */}
            <Outlet context={{ scenario: resource.data, reload: resource.reload }} />
            <div className="flex justify-end"><Link to={next ? `${base}/${next.segment}` : '/goals/scenarios'} className={primaryClass}>{next ? tr('次へ', 'Next') : tr('シナリオ一覧へ', 'To scenarios')}</Link></div>
        </>}
    </div>;
}

export default function ScenarioLayout() {
    const { clientId } = useClient();
    const { scenarioId = '' } = useParams();
    return <ScenarioForClient key={`${clientId}:${scenarioId}`} scenarioId={scenarioId} />;
}
