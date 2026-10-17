import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createGoalCapsule } from '../../../api';
import { goalPreview, makeGoal, type GoalPreview } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { assetErrorMessage } from '../../useResource';
import { useMutation } from '../db/forms';
import GoalSwitchOverlay, { type PendingGoal } from './GoalSwitchOverlay';

/** Make a scenario the goal after showing what happens to real money.
 *
 * Moves, detachments and events left without a capsule are all shown before
 * anything changes; capsules for the checked events are created right after the
 * switch, because the server only lets capsules attach to goal events. Unchecked
 * ones can still be created later from each life event.
 */
export function useMakeScenarioGoal(onSuccess: () => void): ReturnType<typeof useMutation> & { chooseGoal: (id: number) => void; dialog: ReactNode } {
    const mutation = useMutation();
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [pending, setPending] = useState<PendingGoal | null>(null);
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);
    const chooseGoal = (id: number) => {
        let preview: GoalPreview | null = null;
        void mutation.run(async () => { preview = await goalPreview(id); }, '', () => {
            const loaded: GoalPreview | null = preview;
            if (loaded) setPending({ preview: loaded, create: new Set(loaded.missing.map((row) => row.event_id)) });
        });
    };
    const confirmGoal = () => {
        if (!pending) return;
        const { preview, create } = pending;
        let partial = false;
        void mutation.run(async () => {
            // The overlay already showed every detachment, so confirming it is explicit.
            await makeGoal(preview.scenario_id, preview.detach.length > 0);
            const failed: string[] = [];
            for (const row of preview.missing) {
                if (!create.has(row.event_id)) continue;
                try {
                    await createGoalCapsule(row.event_id);
                } catch (failure: unknown) {
                    failed.push(`${row.event_name}（${assetErrorMessage(failure)}）`);
                }
            }
            if (failed.length) {
                partial = true;
                throw new Error(`ゴールにしましたが、取り置きを作成できなかったライフイベントがあります：${failed.join('、')}。ライフイベントの画面から作成できます。`);
            }
        }, 'ゴールにしました。', () => { setPending(null); onSuccess(); }).finally(() => {
            // The goal changed even though a capsule failed; refresh and close anyway.
            if (partial && mounted.current) { setPending(null); onSuccess(); }
        });
    };
    const dialog = pending && <GoalSwitchOverlay pending={pending} busy={mutation.busy} currency={currency}
        onClose={() => setPending(null)} onConfirm={confirmGoal}
        onToggle={(eventId, checked) => setPending((previous) => {
            if (!previous) return previous;
            const next = new Set(previous.create);
            if (checked) next.add(eventId); else next.delete(eventId);
            return { ...previous, create: next };
        })} />;
    return { ...mutation, chooseGoal, dialog };
}
