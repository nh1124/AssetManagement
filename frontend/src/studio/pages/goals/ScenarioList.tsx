import { useCallback, useRef, useState, type MouseEvent } from 'react';
import { Flag, MoreHorizontal } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { LifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';
import ContextMenu from './ContextMenu';
import ScenarioNameEditor from './ScenarioNameEditor';
import { lowestProbability } from './scenarioSimulation';
import { useMakeScenarioGoal } from './useMakeScenarioGoal';

type NameDialog = { mode: 'create' } | { mode: 'rename' | 'duplicate'; scenario: LifeScenario };

function ScenariosForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const navigate = useNavigate();
    const confirm = useConfirm();
    const load = useCallback(async () => {
        const scenarios = await scenariosApi.list();
        const comparison = scenarios.length ? await scenariosApi.compare(scenarios.map((row) => row.id)) : { scenarios: [] };
        return { scenarios, comparison: comparison.scenarios };
    }, []);
    const resource = useResource(load);
    const mutation = useMutation();
    const goal = useMakeScenarioGoal(resource.reload);
    const [checked, setChecked] = useState<number[] | null>(null);
    const [dialog, setDialog] = useState<NameDialog | null>(null);
    const [menu, setMenu] = useState<{ x: number; y: number; scenario: LifeScenario } | null>(null);
    const trigger = useRef<HTMLElement | null>(null);
    const scenarios = [...(resource.data?.scenarios ?? [])].sort((a, b) => Number(b.is_goal) - Number(a.is_goal) || a.id - b.id);
    const ids = (checked ?? scenarios.filter((row) => row.is_goal).map((row) => row.id)).filter((id) => scenarios.some((row) => row.id === id));
    const figures = new Map(resource.data?.comparison.map((row) => [row.id, row]));
    const busy = mutation.busy || goal.busy;
    const disabled = busy || resource.loading || Boolean(resource.error) || !clientName;
    const closeMenu = () => { setMenu(null); trigger.current?.focus(); };
    const openMenu = (event: MouseEvent<HTMLElement>, scenario: LifeScenario, atButton = false) => {
        event.preventDefault();
        event.stopPropagation();
        if (disabled) return;
        trigger.current = atButton ? event.currentTarget : event.currentTarget.querySelector<HTMLAnchorElement>('a');
        const bounds = event.currentTarget.getBoundingClientRect();
        setMenu({ scenario, x: atButton ? bounds.left : event.clientX, y: atButton ? bounds.bottom : event.clientY });
    };
    const closeDialog = () => setDialog(null);
    const saveName = (name: string) => {
        if (!dialog || disabled) return;
        let saved: LifeScenario | undefined;
        void mutation.run(async () => {
            saved = dialog.mode === 'create' ? await scenariosApi.create(name)
                : dialog.mode === 'duplicate' ? await scenariosApi.duplicate(dialog.scenario.id, name)
                    : await scenariosApi.update(dialog.scenario.id, { name });
        }, '', () => {
            setDialog(null);
            if (saved && dialog.mode !== 'rename') navigate(`/goals/scenarios/${saved.id}/events`);
            else resource.reload();
        });
    };
    return <section className="space-y-5">
        <Link to="/goals" className={`inline-block ${buttonClass}`}>ゴールに戻る</Link>
        <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">シナリオ一覧</h2>
            <button type="button" disabled={disabled} onClick={() => setDialog({ mode: 'create' })} className={buttonClass}>新しいシナリオ</button>
        </div>
        <Feedback loading={resource.loading} error={resource.error || mutation.error || goal.error} message={goal.message} />
        {goal.dialog}
        {resource.data && <DataTable columns={['比較', '名称', 'イベント数', '最終純資産（中央値）', '条件の達成確率', '']}>
            {scenarios.map((scenario) => {
                const projected = figures.get(scenario.id);
                const lowest = projected ? lowestProbability(projected) : null;
                const path = `/goals/scenarios/${scenario.id}/events`;
                return <tr key={`scenario-${scenario.id}`} className="cursor-pointer hover:bg-[var(--studio-accent-soft)]" onClick={() => navigate(path)} onContextMenu={(event) => openMenu(event, scenario)}>
                    <td className="px-5 py-3" onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`${scenario.name}を比較する`} checked={ids.includes(scenario.id)} disabled={disabled} onChange={(event) => setChecked(event.target.checked ? [...ids, scenario.id] : ids.filter((id) => id !== scenario.id))} className="accent-[var(--studio-accent)]" /></td>
                    <th scope="row" className="px-5 py-3 font-medium"><Link to={path} onClick={(event) => event.stopPropagation()} className="inline-flex items-center gap-2 rounded text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{scenario.is_goal && <Flag size={14} aria-label="ゴール" />}{scenario.name}</Link></th>
                    <td className="px-5 py-3 tabular-nums">{scenario.events.length}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{projected?.projection.length ? formatCurrency(projected.projection.at(-1)?.p50, currency) : '—'}</td>
                    <td className="px-5 py-3 tabular-nums">{lowest === null ? '—' : `${Math.round(lowest * 100)}%`}</td>
                    <td className="px-5 py-3"><button type="button" disabled={disabled} aria-label={`「${scenario.name}」の操作`} aria-haspopup="menu" aria-expanded={menu?.scenario.id === scenario.id} onClick={(event) => openMenu(event, scenario, true)} className="rounded p-1.5 hover:bg-[var(--studio-accent-soft)] disabled:opacity-40"><MoreHorizontal size={18} aria-hidden="true" /></button></td>
                </tr>;
            })}
            {scenarios.length === 0 && <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">シナリオはありません。</td></tr>}
        </DataTable>}
        <div className="flex justify-end"><button type="button" disabled={disabled || ids.length < 2} onClick={() => navigate(`/goals/compare?ids=${ids.join(',')}`)} className={primaryClass}>比較する</button></div>
        {menu && !disabled && <ContextMenu viewport label="シナリオの操作" x={menu.x} y={menu.y} onClose={closeMenu} items={[
            { label: '名前を変更', onSelect: () => setDialog({ mode: 'rename', scenario: menu.scenario }) },
            { label: '複製', onSelect: () => setDialog({ mode: 'duplicate', scenario: menu.scenario }) },
            ...(!menu.scenario.is_goal ? [{ label: 'ゴールにする', onSelect: () => goal.chooseGoal(menu.scenario.id) }] : []),
            { label: '削除', onSelect: () => {
                const scenario = menu.scenario;
                void (async () => {
                    if (await confirm(`「${clientName}」のシナリオ「${scenario.name}」を削除します。`, '削除')) {
                        await mutation.run(() => scenariosApi.remove(scenario.id), '', resource.reload);
                    }
                })();
            } },
        ]} />}
        {dialog && <Overlay title={dialog.mode === 'create' ? '新しいシナリオ' : dialog.mode === 'rename' ? '名前を変更' : 'シナリオを複製'} busy={busy} onClose={closeDialog}>
            <Feedback error={mutation.error} />
            <ScenarioNameEditor initialName={dialog.mode === 'create' ? '' : dialog.mode === 'rename' ? dialog.scenario.name : `${dialog.scenario.name}のコピー`} busy={disabled} onSave={saveName} onCancel={closeDialog} />
        </Overlay>}
    </section>;
}

export default function ScenarioList() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <ScenariosForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
