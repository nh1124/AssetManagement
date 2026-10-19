import { deleteGoal } from '../../../api';
import type { LifeEvent } from '../../../types';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { Feedback } from '../db/Database';
import { useMutation } from '../db/forms';
import GoalEditor from './GoalEditor';

/** The life event editor in an overlay, with deletion inside it; the list and the diagram share it. */
export default function LifeEventOverlay({ event, scenarioId, events, currency, clientName, onClose, onChanged }: {
    event: LifeEvent | null; scenarioId: number; events: LifeEvent[]; currency: string; clientName: string;
    onClose: () => void; onChanged: () => void;
}) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const done = () => { onClose(); onChanged(); };
    const remove = event ? () => {
        void (async () => {
            // Links, preconditions and its withdrawal records go with the event; its earmark stays, no longer the goal's.
            if (await confirm(`「${clientName}」のライフイベント「${event.name}」を削除します。接続・前提条件・このイベントへの取り崩しのレコードも削除します（取り置きは残ります）。`, '削除する')) {
                await mutation.run(() => deleteGoal(event.id), '', done);
            }
        })();
    } : undefined;
    return <Overlay title={event ? `「${event.name}」を編集` : '新しいライフイベント'} busy={mutation.busy} onClose={onClose}>
        <Feedback error={mutation.error} />
        <GoalEditor goal={event} scenarioId={scenarioId} events={events} currency={currency} busy={mutation.busy}
            onCancel={onClose} onDelete={remove} onSave={(action) => { void mutation.run(action, '', done); }} />
    </Overlay>;
}
