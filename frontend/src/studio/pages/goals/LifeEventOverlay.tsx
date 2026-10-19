import { deleteGoal } from '../../../api';
import type { LifeEvent } from '../../../types';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { Feedback } from '../db/Database';
import { useMutation, type DatabaseAccount } from '../db/forms';
import GoalEditor from './GoalEditor';

/** The life event editor in an overlay, with deletion inside it; the list and the diagram share it. */
export default function LifeEventOverlay({ event, scenarioId, events, accounts, currency, clientName, onClose, onChanged }: {
    event: LifeEvent | null; scenarioId: number; events: LifeEvent[]; accounts: DatabaseAccount[]; currency: string; clientName: string;
    onClose: () => void; onChanged: () => void;
}) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const done = () => { onClose(); onChanged(); };
    const remove = event ? () => {
        void (async () => {
            // Links and preconditions go with the event; its earmark stays, no longer the goal's.
            if (await confirm(`「${clientName}」のライフイベント「${event.name}」を削除します。接続・前提条件も削除します（取り置きは残ります）。`, '削除する')) {
                await mutation.run(() => deleteGoal(event.id), '', done);
            }
        })();
    } : undefined;
    return <Overlay title={event ? `「${event.name}」を編集` : '新しいライフイベント'} busy={mutation.busy} onClose={onClose}>
        <Feedback error={mutation.error} />
        <GoalEditor goal={event} scenarioId={scenarioId} events={events} accounts={accounts} currency={currency} busy={mutation.busy}
            onCancel={onClose} onDelete={remove} onSave={(action) => { void mutation.run(action, '', done); }} />
    </Overlay>;
}
