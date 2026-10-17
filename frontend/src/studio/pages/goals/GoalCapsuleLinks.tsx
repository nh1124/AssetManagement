import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { createCapsule, getCapsules, getLifeEvents, updateCapsule } from '../../../api';
import type { Capsule, LifeEvent } from '../../../types';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { assetErrorMessage, useResource } from '../../useResource';
import { DataTable, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';

async function loadAllCapsules() {
    const rows: Capsule[] = [];
    // The default endpoint returns only 100 rows, but linking must offer every capsule.
    for (let skip = 0; ; skip += 100) {
        const page = await getCapsules(skip, 100);
        rows.push(...page);
        if (page.length < 100) return rows;
    }
}

/** A capsule for this event, prefilled from it so most users only press save. */
function NewCapsuleForm({ goal, onCreated, onBack }: {
    goal: LifeEvent; onCreated: (capsule: Capsule) => void; onBack: () => void;
}) {
    const formId = useId();
    const mutation = useMutation();
    const [name, setName] = useState(goal.name);
    const [target, setTarget] = useState(String(goal.target_amount ?? 0));
    const [monthly, setMonthly] = useState('');
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (mutation.busy || !name.trim()) return;
        let created: Capsule | null = null;
        void mutation.run(async () => {
            // Created already linked, so the list it returns to cannot unlink it by accident.
            created = await createCapsule({
                name: name.trim(), target_amount: Number(target),
                monthly_contribution: monthly.trim() === '' ? 0 : Number(monthly), life_event_id: goal.id,
            });
        }, '取り置きを作成しました。', () => { if (created) onCreated(created); });
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <button type="button" disabled={mutation.busy} onClick={onBack} className={buttonClass}>一覧に戻る</button>
        <Feedback error={mutation.error} />
        <fieldset disabled={mutation.busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label="目標額"><input required type="number" min="0" step="any" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <Field label="月額積立（任意）"><input type="number" min="0" step="any" value={monthly} onChange={(event) => setMonthly(event.target.value)} className={inputClass} /></Field>
        </fieldset>
        <EditorActions form={formId} busy={mutation.busy} onCancel={onBack} />
    </form>;
}

function CapsuleLinkEditor({ goal, capsules, goals, onClose, onChanged, onBusy }: {
    goal: LifeEvent; capsules: Capsule[]; goals: LifeEvent[];
    onClose: () => void; onChanged: () => void; onBusy: (busy: boolean) => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const mutation = useMutation();
    const inFlight = useRef(false);
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        // A route or client switch must stop the remaining independently committed writes.
        return () => { mounted.current = false; };
    }, []);
    const [rows, setRows] = useState(capsules);
    const [creating, setCreating] = useState(false);
    const [selected, setSelected] = useState(() => new Set(capsules.filter((row) => row.life_event_id === goal.id).map((row) => row.id)));
    const eventName = (id: number, events = goals) => events.find((event) => event.id === id)?.name ?? `ライフイベント #${id}`;
    const save = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (inFlight.current) return;
        inFlight.current = true;
        onBusy(true);
        let completed = false;
        let saved = 0;
        void mutation.run(async () => {
            const intended = rows.filter((row) => selected.has(row.id) !== (row.life_event_id === goal.id));
            const [current, currentGoals] = await Promise.all([loadAllCapsules(), getLifeEvents(true)]);
            if (!mounted.current) return;
            const changes = intended.flatMap((row) => {
                const fresh = current.find((candidate) => candidate.id === row.id);
                if (!fresh) throw new Error(`「${row.name}」が見つかりません。開き直してください。`);
                const target = selected.has(row.id) ? goal.id : null;
                if ((fresh.life_event_id ?? null) === target) return [];
                // A stale unlink must never remove a link somebody moved to another event.
                if (target === null && fresh.life_event_id !== goal.id) throw new Error(`「${row.name}」の紐づけ先が変わりました。開き直してください。`);
                return [{ row: fresh, target }];
            });
            const moves = changes.flatMap(({ row, target }) => target === goal.id && row.life_event_id != null && row.life_event_id !== goal.id ? [{ name: row.name, eventId: row.life_event_id }] : []);
            if (moves.length && !(await confirm(
                `${moves.map(({ name, eventId }) => `「${name}」：${eventName(eventId, currentGoals)} → ${goal.name}`).join('\n')}\n取り置きの紐づけ先を移動しますか？`,
                '移動して保存', '取り置きの紐づけを移動',
            ))) return;
            try {
                // These updates commit individually; retain each success so retries only send pending changes.
                for (const { row, target } of changes) {
                    if (!mounted.current) return;
                    const updated = await updateCapsule(row.id, { life_event_id: target });
                    saved += 1;
                    setRows((previous) => previous.map((candidate) => candidate.id === updated.id ? updated : candidate));
                }
                completed = true;
            } catch (failure: unknown) {
                throw new Error(`${saved}件を保存しました。未保存の変更を再試行できます。${assetErrorMessage(failure)}`);
            } finally {
                if ((saved || completed) && mounted.current) onChanged();
            }
        }, '取り置きの紐づけを保存しました。', () => { if (completed) onClose(); })
            .finally(() => { inFlight.current = false; onBusy(false); });
    };
    if (creating) return <NewCapsuleForm goal={goal} onBack={() => setCreating(false)} onCreated={(capsule) => {
        setRows((previous) => [...previous, capsule]);
        setSelected((previous) => new Set(previous).add(capsule.id));
        setCreating(false);
        onChanged();
    }} />;
    return <form id={formId} onSubmit={save} className="space-y-4">
        <button type="button" disabled={mutation.busy} onClick={() => setCreating(true)} className={buttonClass}>新しい取り置き</button>
        <Feedback error={mutation.error} />
        <fieldset disabled={mutation.busy}>
            <DataTable columns={['紐づける', '取り置き', '現在のライフイベント']}>
                {rows.length ? rows.map((row) => <tr key={row.id}>
                    <td className="px-5 py-3"><input type="checkbox" aria-label={`${row.name}を紐づける`} checked={selected.has(row.id)} onChange={(event) => setSelected((previous) => {
                        const next = new Set(previous);
                        if (event.target.checked) next.add(row.id); else next.delete(row.id);
                        return next;
                    })} /></td>
                    <th scope="row" className="px-5 py-3 font-medium">{row.name}</th>
                    <td className="px-5 py-3">{row.life_event_id == null ? '—' : eventName(row.life_event_id)}</td>
                </tr>) : <tr><td colSpan={3} className="px-5 py-4 text-[var(--studio-text-muted)]">取り置きはありません。</td></tr>}
            </DataTable>
        </fieldset>
        <EditorActions form={formId} busy={mutation.busy} onCancel={onClose} />
    </form>;
}

export default function GoalCapsuleLinks({ goal, busy, onClose, onChanged, onBusy }: {
    goal: LifeEvent; busy: boolean;
    onClose: () => void; onChanged: () => void; onBusy: (busy: boolean) => void;
}) {
    const load = useCallback(async () => {
        const [capsules, goals] = await Promise.all([loadAllCapsules(), getLifeEvents(true)]);
        return { capsules, goals };
    }, []);
    const resource = useResource(load);
    return <Overlay title="取り置きを紐づける" busy={busy} onClose={onClose}>
        <Feedback loading={resource.loading} error={resource.error} />
        {!resource.loading && !resource.error && resource.data && <CapsuleLinkEditor goal={goal} {...resource.data} onClose={onClose} onChanged={onChanged} onBusy={onBusy} />}
    </Overlay>;
}
