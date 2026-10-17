import { useCallback, useEffect, useRef, useState } from 'react';
import { getLifeEventsWithProgress } from '../../../api';
import { adoptLifeEventScenario, getLifeEventScenarios, type ScenarioComparison, type ScenarioParameters } from '../../../api/lifeEventGraph';
import { getSimulationConfig, putSimulationConfig, type SimulationConfig } from '../../../api/simulationConfig';
import { useClient } from '../../../context/ClientContext';
import { assetErrorMessage, useResource } from '../../useResource';
import { Feedback, Field } from '../db/Database';
import { inputClass, primaryClass, useMutation } from '../db/forms';
import Comparison from './Comparison';
import NoLifeEvents from './NoLifeEvents';

type Draft = Record<keyof ScenarioParameters, string>;

function parseParameters(draft: Draft): ScenarioParameters | null {
    if (Object.values(draft).some((value) => !value.trim())) return null;
    const years = Number(draft.years);
    const annual_return = Number(draft.annual_return);
    const inflation = Number(draft.inflation);
    if (!Number.isInteger(years) || years < 1 || years > 60 || !Number.isFinite(annual_return) || !Number.isFinite(inflation)) return null;
    return { years, annual_return, inflation };
}

function SimulationEditor({ config, initial, currency, clientName }: { config: SimulationConfig; initial: ScenarioComparison; currency: string; clientName?: string }) {
    const [draft, setDraft] = useState<Draft>({ years: String(config.horizon_years), annual_return: String(config.annual_return), inflation: String(config.inflation_rate) });
    const [comparison, setComparison] = useState(initial);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const revision = useRef(0);
    // The newest valid values not yet saved. The debounce delays the write, so
    // without this a value typed just before leaving the page would be lost --
    // and these numbers are meant to be stored, not a scratch preview.
    const unsaved = useRef<ScenarioParameters | null>(null);
    const saveQueue = useRef<Promise<void>>(Promise.resolve());
    const mounted = useRef(false);
    const mutation = useMutation();
    const parameters = parseParameters(draft);
    const validation = parameters ? '' : '期間は1〜60の整数、年利・インフレは有限の数値で入力してください。';
    const selected = comparison.scenarios.find((scenario) => scenario.id === comparison.adopted.scenario_id);
    const disabled = pending || Boolean(validation) || Boolean(error) || mutation.busy || !clientName;

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            const values = unsaved.current;
            if (!values) return;
            unsaved.current = null;
            void saveQueue.current.then(async () => {
                const stored = await getSimulationConfig();
                await putSimulationConfig({ ...stored, horizon_years: values.years, annual_return: values.annual_return, inflation_rate: values.inflation });
            }).catch(() => {});
        };
    }, []);

    useEffect(() => {
        const values = parseParameters(draft);
        if (revision.current === 0 || !values || !clientName) return;
        const request = revision.current;
        let cancelled = false;
        const current = () => !cancelled && request === revision.current;
        const timer = window.setTimeout(() => {
            const projection = getLifeEventScenarios(values).then((result) => {
                if (current()) setComparison(result);
            });
            // Serialize writes so a slow older PUT cannot overwrite a newer configuration.
            const saving = saveQueue.current.then(async () => {
                if (!current()) return;
                const stored = await getSimulationConfig();
                if (!current()) return;
                // PUT defaults every omitted field; preserve all other stored assumptions.
                await putSimulationConfig({ ...stored, horizon_years: values.years, annual_return: values.annual_return, inflation_rate: values.inflation });
                if (current()) {
                    unsaved.current = null;
                    setMessage('保存しました');
                }
            });
            // A failed save must not prevent subsequent edits from being saved.
            saveQueue.current = saving.catch(() => {});
            void Promise.allSettled([projection, saving]).then((results) => {
                if (!current()) return;
                const failures = results.flatMap((result) => result.status === 'rejected' ? [assetErrorMessage(result.reason)] : []);
                setError([...new Set(failures)].join('、'));
                setPending(false);
            });
        }, 400);
        return () => { cancelled = true; window.clearTimeout(timer); };
    }, [draft, clientName]);

    const change = (field: keyof Draft, value: string) => {
        const next = { ...draft, [field]: value };
        // Invalidate at the keystroke, before the next effect or debounce can run.
        revision.current += 1;
        unsaved.current = parseParameters(next);
        setDraft(next);
        setPending(Boolean(parseParameters(next)) && Boolean(clientName));
        setError('');
        setMessage('');
    };
    const adopt = (scenarioId: string) => {
        if (disabled || !scenarioId || !parameters) return;
        const request = revision.current;
        void mutation.run(async () => {
            await adoptLifeEventScenario(scenarioId);
            const result = await getLifeEventScenarios(parameters);
            if (mounted.current && request === revision.current) setComparison(result);
        }, 'ゴールにする案を保存しました。');
    };

    return <section className="space-y-5">
        <fieldset disabled={mutation.busy || !clientName} className="grid gap-4 sm:grid-cols-3">
            <Field label="期間（年）"><input type="number" min="1" max="60" step="1" required value={draft.years} onChange={(event) => change('years', event.target.value)} className={inputClass} /></Field>
            <Field label="年利（%）"><input type="number" step="any" required value={draft.annual_return} onChange={(event) => change('annual_return', event.target.value)} className={inputClass} /></Field>
            <Field label="インフレ（%）"><input type="number" step="any" required value={draft.inflation} onChange={(event) => change('inflation', event.target.value)} className={inputClass} /></Field>
        </fieldset>
        <Feedback error={validation || error || mutation.error} message={mutation.message} />
        {message && <p role="status" className="text-xs text-[var(--studio-text-muted)]">{message}</p>}
        {pending && <p role="status" className="text-xs text-[var(--studio-text-muted)]">試算・保存中…</p>}
        {!comparison.adopted.exact && <p role="status" className="text-sm text-[var(--studio-warning)]">分岐の選択がまだ確定していません。</p>}
        {comparison.truncated && <p role="status" className="text-sm text-[var(--studio-warning)]">{comparison.fork_count}か所の分岐で64案を超えたため、先頭64案を表示しています。</p>}
        <div aria-busy={pending} className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <Comparison scenarios={comparison.scenarios} currency={currency} />
        </div>
        <div className="flex flex-wrap items-end justify-end gap-3">
            <Field label="ゴールにする案"><select value={comparison.adopted.scenario_id ?? ''} onChange={(event) => adopt(event.target.value)} disabled={disabled} className={inputClass}>
                {comparison.adopted.scenario_id === null && <option value="" disabled>未選択</option>}
                {comparison.scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.label}</option>)}
            </select></Field>
            {/* Re-selecting the provisional option cannot fire onChange; keep an explicit action. */}
            <button type="button" disabled={disabled || !selected} onClick={() => { if (selected) adopt(selected.id); }} className={primaryClass}>この案をゴールにする</button>
        </div>
    </section>;
}

function SimulationForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const load = useCallback(async () => {
        const [config, comparison, events] = await Promise.all([getSimulationConfig(), getLifeEventScenarios(), getLifeEventsWithProgress(false)]);
        return { config, comparison, events };
    }, []);
    const resource = useResource(load);
    return <>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && !resource.loading && !resource.error && (
            resource.data.events.length === 0 && resource.data.comparison.scenarios.every((scenario) => scenario.events.length === 0) ? <NoLifeEvents />
                : <SimulationEditor config={resource.data.config} initial={resource.data.comparison} currency={currency} clientName={clientName} />
        )}
    </>;
}

export default function Simulation() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SimulationForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
