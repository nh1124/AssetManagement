import { useId, useRef, useState, type MouseEvent } from 'react';
import { Flag, MoreHorizontal } from 'lucide-react';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { LifeScenario } from '../../../api/lifeScenarios';
import type { LifeEventLink } from '../../../api/lifeEventGraph';
import type { LifeEvent } from '../../../types';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass } from '../db/forms';
import ContextMenu from './ContextMenu';

type NameDialog = { mode: 'create' } | { mode: 'rename' | 'duplicate'; scenario: LifeScenario };

function ScenarioNameEditor({ initialName, busy, onSave, onCancel }: {
    initialName: string; busy: boolean; onSave: (name: string) => void; onCancel: () => void;
}) {
    const form = useId();
    const [name, setName] = useState(initialName);
    return <form id={form} onSubmit={(event) => {
        event.preventDefault();
        if (!busy && name.trim()) onSave(name.trim());
    }}>
        <Field label="名前"><input required autoFocus value={name} disabled={busy} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
        <EditorActions form={form} busy={busy || !name.trim()} onCancel={onCancel} />
    </form>;
}

export default function ScenarioBar({ scenarios, selected, events, links, clientName, disabled, busy, error, onSelect, onChoose, onRun }: {
    scenarios: LifeScenario[]; selected?: LifeScenario; events: LifeEvent[]; links: LifeEventLink[];
    clientName?: string; disabled: boolean; busy: boolean; error: string;
    onSelect: (id: number) => void; onChoose: (link: LifeEventLink) => void;
    onRun: (action: () => Promise<unknown>, message: string, onSuccess?: () => void) => void;
}) {
    const confirm = useConfirm();
    const [dialog, setDialog] = useState<NameDialog | null>(null);
    const [menu, setMenu] = useState<{ x: number; y: number; scenario: LifeScenario } | null>(null);
    const trigger = useRef<HTMLButtonElement | null>(null);
    const names = new Map(events.map((event) => [event.id, event.name]));
    const alternatives = new Map<number, LifeEventLink[]>();
    for (const link of links) {
        if (link.kind === 'alternative' && names.has(link.from_event_id) && names.has(link.to_event_id)) {
            alternatives.set(link.from_event_id, [...(alternatives.get(link.from_event_id) ?? []), link]);
        }
    }
    const forks = [...alternatives].filter(([, outgoing]) => outgoing.length >= 2);
    const openMenu = (event: MouseEvent<HTMLButtonElement>, scenario: LifeScenario, atButton = false) => {
        event.preventDefault();
        if (disabled) return;
        trigger.current = event.currentTarget;
        const bounds = event.currentTarget.getBoundingClientRect();
        setMenu({ scenario, x: atButton ? bounds.left : event.clientX, y: atButton ? bounds.bottom : event.clientY });
    };
    const closeMenu = () => { setMenu(null); trigger.current?.focus(); };
    const saveName = (name: string) => {
        if (!dialog || disabled) return;
        let saved: LifeScenario | undefined;
        onRun(async () => {
            saved = dialog.mode === 'create' ? await scenariosApi.create(name)
                : dialog.mode === 'duplicate' ? await scenariosApi.duplicate(dialog.scenario.id, name)
                    : await scenariosApi.update(dialog.scenario.id, { name });
        }, dialog.mode === 'create' ? 'シナリオを作成しました。' : dialog.mode === 'duplicate' ? 'シナリオを複製しました。' : '名前を変更しました。', () => {
            if (saved && dialog.mode !== 'rename') onSelect(saved.id);
            setDialog(null);
        });
    };
    return <div className="space-y-3">
        <div role="group" aria-label="シナリオ" className="flex flex-wrap items-center gap-2">
            {[...scenarios].sort((left, right) => Number(right.is_goal) - Number(left.is_goal) || left.id - right.id).map((scenario) => <div key={`scenario-${scenario.id}`} className={`flex items-center rounded-full border border-[var(--studio-border)] ${selected?.id === scenario.id ? 'bg-[var(--studio-accent-soft)] ring-1 ring-[var(--studio-accent)]' : ''}`}>
                <button type="button" disabled={disabled} aria-pressed={selected?.id === scenario.id} onClick={() => onSelect(scenario.id)} onContextMenu={(event) => openMenu(event, scenario)} className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm disabled:opacity-40">
                    {scenario.is_goal && <Flag size={14} aria-label="ゴール" />}<span>{scenario.name}</span>
                </button>
                <button type="button" disabled={disabled} aria-label={`「${scenario.name}」の操作`} aria-haspopup="menu" aria-expanded={menu?.scenario.id === scenario.id} onClick={(event) => openMenu(event, scenario, true)} className="mr-1 rounded-full p-1.5 hover:bg-[var(--studio-accent-soft)] disabled:opacity-40"><MoreHorizontal size={16} aria-hidden="true" /></button>
            </div>)}
            <button type="button" disabled={disabled} onClick={() => setDialog({ mode: 'create' })} className={buttonClass}>新しいシナリオ</button>
        </div>
        {Boolean(selected?.missing_forks.length) && <div role="status" className="text-sm text-[var(--studio-warning)]">未選択の分岐があります：{selected?.missing_forks.map((id) => names.get(id) ?? `#${id}`).join('、')}</div>}
        {forks.length > 0 && <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <span className="font-medium">分岐の選択</span>
            {forks.map(([id, outgoing]) => <div key={`fork-${id}`} role="group" aria-label={`${names.get(id)}の分岐`} className="flex flex-wrap items-center gap-2">
                <span>{names.get(id)}</span><div className="flex flex-wrap overflow-hidden rounded-md border border-[var(--studio-border)]">
                    {outgoing.map((link) => <button key={`choice-${link.id}`} type="button" disabled={disabled || !selected} aria-pressed={selected?.choices.includes(link.id) ?? false} onClick={() => onChoose(link)} className="px-3 py-1.5 text-xs hover:bg-[var(--studio-accent-soft)] aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)] disabled:opacity-40">{names.get(link.to_event_id)}</button>)}
                </div>
            </div>)}
        </div>}
        {menu && !disabled && <ContextMenu viewport label="シナリオの操作" x={menu.x} y={menu.y} onClose={closeMenu} items={[
            { label: '名前を変更', onSelect: () => setDialog({ mode: 'rename', scenario: menu.scenario }) },
            { label: '複製', onSelect: () => setDialog({ mode: 'duplicate', scenario: menu.scenario }) },
            { label: '削除', onSelect: () => {
                const scenario = menu.scenario;
                void (async () => {
                    if (await confirm(`「${clientName}」のシナリオ「${scenario.name}」を削除します。`, '削除')) {
                        onRun(() => scenariosApi.remove(scenario.id), 'シナリオを削除しました。');
                    }
                })();
            } },
        ]} />}
        {dialog && <Overlay title={dialog.mode === 'create' ? '新しいシナリオ' : dialog.mode === 'rename' ? '名前を変更' : 'シナリオを複製'} onClose={() => { if (!busy) setDialog(null); }}>
            <Feedback error={error} />
            <ScenarioNameEditor initialName={dialog.mode === 'create' ? '' : dialog.mode === 'rename' ? dialog.scenario.name : `${dialog.scenario.name}のコピー`} busy={disabled} onSave={saveName} onCancel={() => setDialog(null)} />
        </Overlay>}
    </div>;
}
