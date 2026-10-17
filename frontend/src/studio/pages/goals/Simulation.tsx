import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getAccounts } from '../../../api';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { LifeScenario, ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { Account } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { inputClass } from '../db/forms';
import ScenarioProjectionChart from './ScenarioProjectionChart';
import ScenarioPreconditions from './ScenarioPreconditions';
import { parseParameters, parseReturns, ScenarioSaveQueue, type ParameterDraft, type ReturnDraft } from './scenarioSimulation';

type Draft = { parameters: ParameterDraft; returns: ReturnDraft };

function SimulationEditor({ initial, accounts, currency, clientName }: { initial: LifeScenario[]; accounts: Account[]; currency: string; clientName?: string }) {
    const [drafts, setDrafts] = useState<Record<number, Draft>>(() => Object.fromEntries(initial.map((scenario) => [scenario.id, {
        parameters: { horizon_years: String(scenario.horizon_years), annual_return: String(scenario.annual_return), inflation: String(scenario.inflation) },
        returns: Object.fromEntries(scenario.account_returns.map((row) => [row.account_id, String(row.annual_return)])),
    }])));
    const [comparison, setComparison] = useState<ProjectedLifeScenario[]>([]);
    const [pending, setPending] = useState(true);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [editRevision, setEditRevision] = useState(0);
    const [saver] = useState(() => new ScenarioSaveQueue());
    const revision = useRef(0);
    const mounted = useRef(false);
    const focused = initial[0];
    const focusedId = focused?.id;
    const checkedKey = String(focusedId);
    const draft = focused ? drafts[focused.id] : undefined;
    const projected = comparison.find((scenario) => scenario.id === focusedId);
    const validation = draft && (!parseParameters(draft.parameters) ? '期間は1〜60の整数、年利・インフレは有限の数値で入力してください。' : !parseReturns(draft.returns) ? '口座の利回りは有限の数値で入力してください。' : '');
    const locked = !clientName;

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            revision.current += 1;
            // Flush valid drafts on navigation, even before the debounce has fired.
            void saver.flush().catch(() => {});
        };
    }, [saver]);

    useEffect(() => {
        const request = ++revision.current;
        let cancelled = false;
        const current = () => !cancelled && mounted.current && request === revision.current;
        const timer = window.setTimeout(() => {
            if (!current()) return;
            setPending(true);
            setError('');
            void (async () => {
                try {
                    const saved = await saver.flush();
                    if (!current()) return;
                    if (saved) setMessage('保存しました');
                    const result = checkedKey ? await scenariosApi.compare(checkedKey.split(',').map(Number)) : { scenarios: [] };
                    if (current()) setComparison(result.scenarios);
                } catch (failure: unknown) {
                    if (current()) setError(assetErrorMessage(failure));
                } finally {
                    if (current()) setPending(false);
                }
            })();
        }, editRevision > 0 ? 400 : 0);
        return () => { cancelled = true; window.clearTimeout(timer); };
    }, [checkedKey, editRevision, saver]);

    const changed = (next: Draft) => {
        if (!focused || locked) return;
        // Invalidate at the keystroke so an older response cannot flash over new input.
        revision.current += 1;
        setDrafts({ ...drafts, [focused.id]: next });
        setEditRevision((value) => value + 1);
        setPending(true);
        setError('');
        setMessage('');
    };
    const changeParameter = (field: keyof ParameterDraft, value: string) => {
        if (!focused || !draft || locked) return;
        const parameters = { ...draft.parameters, [field]: value };
        saver.stage(focused.id, { parameters: parseParameters(parameters) ?? undefined });
        changed({ ...draft, parameters });
    };
    const changeReturn = (id: number, value: string) => {
        if (!focused || !draft || locked) return;
        const returns = { ...draft.returns, [id]: value };
        saver.stage(focused.id, { returns: parseReturns(returns) ?? undefined });
        changed({ ...draft, returns });
    };
    return <section className="space-y-5">
        <Feedback error={error} />
        {pending && <p role="status" className="text-xs text-[var(--studio-text-muted)]">試算・保存中…</p>}
        <div aria-busy={pending} className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <ScenarioProjectionChart scenarios={comparison} focusedId={focusedId} currency={currency} colourIds={initial.map((scenario) => scenario.id)} />
        </div>
        {focused && draft && <>
            <section className="space-y-4">
                <h2 className="font-semibold">{focused.name}の前提</h2>
                <fieldset disabled={locked} className="grid gap-4 sm:grid-cols-3">
                    <Field label="期間（年）"><input type="number" min="1" max="60" step="1" required value={draft.parameters.horizon_years} onChange={(event) => changeParameter('horizon_years', event.target.value)} className={inputClass} /></Field>
                    <Field label="年利（%）"><input type="number" step="any" required value={draft.parameters.annual_return} onChange={(event) => changeParameter('annual_return', event.target.value)} className={inputClass} /></Field>
                    <Field label="インフレ（%）"><input type="number" step="any" required value={draft.parameters.inflation} onChange={(event) => changeParameter('inflation', event.target.value)} className={inputClass} /></Field>
                </fieldset>
                <Feedback error={validation} />
                {message && <p role="status" className="text-xs text-[var(--studio-text-muted)]">{message}</p>}
                <h3 className="font-medium">口座ごとの利回り</h3>
                <DataTable columns={['名称', '残高', '利回り（%）']}>
                    {accounts.map((account) => <tr key={`account-return-${account.id}`}>
                        <th scope="row" className="px-5 py-3 font-medium">{account.name}{!account.is_active && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">無効</span>}</th>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(account.balance, currency)}</td>
                        {/* Text preserves incomplete decimal input so it cannot remove an override. */}
                        <td className="w-44 px-5 py-3"><input inputMode="decimal" aria-label={`${account.name}の利回り（%）`} disabled={locked} value={draft.returns[account.id] ?? (account.expected_return === null ? '' : String(account.expected_return))} placeholder={account.expected_return === null ? 'シナリオの年利' : String(account.expected_return)} onChange={(event) => changeReturn(account.id, event.target.value)} className={inputClass} /></td>
                    </tr>)}
                    {accounts.length === 0 && <tr><td colSpan={3} className="px-5 py-3 text-[var(--studio-text-muted)]">資産口座はありません。</td></tr>}
                </DataTable>
            </section>
            {projected ? <ScenarioPreconditions events={projected.conditions} currency={currency} /> : <Feedback loading={pending} />}
        </>}
    </section>;
}

function SimulationForClient({ currency, clientName, scenarioId }: { currency: string; clientName?: string; scenarioId: string }) {
    const load = useCallback(async () => {
        const [scenarios, active, inactive] = await Promise.all([scenariosApi.list(), getAccounts('asset', true), getAccounts('asset', false)]);
        const accounts = [...new Map([...inactive, ...active].map((account) => [account.id, account])).values()].sort((a, b) => a.name.localeCompare(b.name, 'ja'));
        const selected = scenarios.find((scenario) => scenario.id === Number(scenarioId));
        if (!selected) throw new Error('このシナリオは見つかりません。');
        return { scenarios: [selected], accounts };
    }, [scenarioId]);
    const resource = useResource(load);
    return <>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && !resource.loading && !resource.error && <SimulationEditor initial={resource.data.scenarios} accounts={resource.data.accounts} currency={currency} clientName={clientName} />}
    </>;
}

export default function Simulation() {
    const { clientId, currentClient } = useClient();
    const { scenarioId = '' } = useParams();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SimulationForClient key={`${clientId}:${currency}:${scenarioId}`} scenarioId={scenarioId} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
