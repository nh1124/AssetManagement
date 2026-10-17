import { useEffect, useRef } from 'react';
import { isAxiosError } from 'axios';
import { makeGoal } from '../../../api/lifeScenarios';
import { useConfirm } from '../../components/useConfirm';
import { useMutation } from '../db/forms';

type Detach = { capsule_id: number; capsule_name: string; event_name: string };

function detachments(failure: unknown): Detach[] | null {
    if (!isAxiosError<{ detail?: { detach?: unknown }; detach?: unknown }>(failure) || failure.response?.status !== 409) return null;
    const rows = failure.response.data?.detail?.detach ?? failure.response.data?.detach;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    // Validate the conflict before offering permission to unlink real reservations.
    return rows.every((row: unknown): row is Detach => typeof row === 'object' && row !== null
        && 'capsule_id' in row && typeof row.capsule_id === 'number'
        && 'capsule_name' in row && typeof row.capsule_name === 'string'
        && 'event_name' in row && typeof row.event_name === 'string') ? rows : null;
}

export function useMakeScenarioGoal(onSuccess: () => void) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);
    const chooseGoal = (id: number) => {
        let saved = false;
        void mutation.run(async () => {
            try {
                await makeGoal(id);
                saved = true;
            } catch (failure: unknown) {
                // A late conflict must not open a decision for a client that was left.
                if (!mounted.current) return;
                const rows = detachments(failure);
                if (!rows) throw failure;
                const body = rows.map((row) => `${row.capsule_name}（取り置き）は ${row.event_name} に対応するライフイベントが無いため、紐づけを外します`).join('\n');
                if (!await confirm(body, '紐づけを外してゴールにする', 'ゴールにする') || !mounted.current) return;
                // The retry may unlink reservations, so it requires explicit confirmation.
                await makeGoal(id, true);
                saved = true;
            }
        }, '', () => { if (saved) onSuccess(); });
    };
    return { ...mutation, chooseGoal };
}
