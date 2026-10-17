import { useCallback, useEffect, useRef, useState } from 'react';
import { Flag } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { getAccounts } from '../../../api';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { LifeScenario, ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { Account } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { inputClass, primaryClass, useMutation } from '../db/forms';
import Comparison, { MissingForks } from './Comparison';
import NoLifeEvents from './NoLifeEvents';
import ScenarioPreconditions from './ScenarioPreconditions';
import { parseParameters, parseReturns, scenarioSelection, ScenarioSaveQueue, type ParameterDraft, type ReturnDraft } from './scenarioSimulation';

type Draft = { parameters: ParameterDraft; returns: ReturnDraft };

function SimulationEditor({ initial, accounts, currency, clientName }: { initial: LifeScenario[]; accounts: Account[]; currency: string; clientName?: string }) {
    const [scenarios, setScenarios] = useState(initial);
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
    const mutation = useMutation();
    const [search, setSearch] = useSearchParams();
    const { ids, focusedId } = scenarioSelection(scenarios, search);
    const checkedKey = ids.join(',');
    const focused = scenarios.find((scenario) => scenario.id === focusedId);
    const draft = focused ? drafts[focused.id] : undefined;
    const projected = comparison.find((scenario) => scenario.id === focusedId);
    const sorted = [...scenarios].sort((a, b) => Number(b.is_goal) - Number(a.is_goal) || a.id - b.id);
    const validation = draft && (!parseParameters(draft.parameters) ? '期間は1〜60の整数、年利・インフレは有限の数値で入力してください。' : !parseReturns(draft.returns) ? '口座の利回りは有限の数値で入力してください。' : '');
    const locked = mutation.busy || !clientName;

    useEffect(() => {
        const next = new URLSearchParams(search);
        next.set('compare', checkedKey);
        if (focusedId === undefined) next.delete('focus');
        else next.set('focus', String(focusedId));
        if (next.toString() !== search.toString()) setSearch(next, { replace: true });
    }, [checkedKey, focusedId, search, setSearch]);

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

    const choose = (nextIds: number[], nextFocus: number | undefined) => {
        if (nextIds.join(',') !== checkedKey) {
            revision.current += 1;
            setPending(true);
        }
        const next = new URLSearchParams(search);
        next.set('compare', nextIds.join(','));
        if (nextFocus === undefined) next.delete('focus');
        else next.set('focus', String(nextFocus));
        setSearch(next);
    };
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
    const makeGoal = () => {
        if (!focused || locked || pending || validation || error) return;
        void mutation.run(async () => {
            await saver.flush();
            await saver.run(() => scenariosApi.makeGoal(focused.id));
            if (mounted.current) setScenarios((rows) => rows.map((scenario) => ({ ...scenario, is_goal: scenario.id === focused.id })));
        }, 'ゴールにするシナリオを保存しました。');
    };

    return <section className="space-y-5">
        <div role="group" aria-label="比較するシナリオ" className="flex flex-wrap gap-2">
            {sorted.map((scenario) => <div key={`scenario-choice-${scenario.id}`} className={`flex items-center gap-2 rounded-lg border border-[var(--studio-border)] px-3 py-2 ${focusedId === scenario.id ? 'bg-[var(--studio-accent-soft)] ring-1 ring-[var(--studio-accent)]' : ''}`}>
                <input type="checkbox" aria-label={`${scenario.name}を比較する`} checked={ids.includes(scenario.id)} disabled={mutation.busy} onChange={(event) => {
                    const next = event.target.checked ? [...ids, scenario.id] : ids.filter((id) => id !== scenario.id);
                    choose(next, next.includes(focusedId ?? -1) ? focusedId : next[0]);
                }} className="accent-[var(--studio-accent)]" />
                <button type="button" aria-pressed={focusedId === scenario.id} disabled={mutation.busy} onClick={() => choose(ids.includes(scenario.id) ? ids : [...ids, scenario.id], scenario.id)} className="flex items-center gap-1.5 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">
                    {scenario.is_goal && <Flag size={14} aria-label="ゴール" />}{scenario.name}
                </button>
            </div>)}
        </div>
        <Feedback error={error || mutation.error} message={mutation.message} />
        {pending && <p role="status" className="text-xs text-[var(--studio-text-muted)]">試算・保存中…</p>}
        {ids.length === 0 ? <p className="text-sm text-[var(--studio-text-muted)]">比較するシナリオを選んでください。</p> : <div aria-busy={pending} className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <Comparison scenarios={comparison.filter((scenario) => ids.includes(scenario.id)).map((scenario) => ({ ...scenario, is_goal: scenarios.find((row) => row.id === scenario.id)?.is_goal ?? false }))} focusedId={focusedId} currency={currency} colourIds={initial.map((scenario) => scenario.id)} />
        </div>}
        {focused && draft && <>
            <section className="space-y-4">
                <h2 className="font-semibold">{focused.name}の前提</h2>
                <MissingForks scenario={focused} />
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
                <div className="flex justify-end"><button type="button" disabled={locked || pending || Boolean(validation) || Boolean(error) || focused.is_goal} onClick={makeGoal} className={primaryClass}>このシナリオをゴールにする</button></div>
            </section>
            {projected ? <ScenarioPreconditions events={projected.conditions} currency={currency} /> : <Feedback loading={pending} />}
        </>}
    </section>;
}

function SimulationForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const load = useCallback(async () => {
        const [scenarios, active, inactive] = await Promise.all([scenariosApi.list(), getAccounts('asset', true), getAccounts('asset', false)]);
        const accounts = [...new Map([...inactive, ...active].map((account) => [account.id, account])).values()].sort((a, b) => a.name.localeCompare(b.name, 'ja'));
        return { scenarios, accounts };
    }, []);
    const resource = useResource(load);
    return <>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && !resource.loading && !resource.error && (resource.data.scenarios.length === 0 ? <NoLifeEvents noScenarios />
            : <SimulationEditor initial={resource.data.scenarios} accounts={resource.data.accounts} currency={currency} clientName={clientName} />)}
    </>;
}

export default function Simulation() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SimulationForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
