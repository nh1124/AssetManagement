import { useCallback } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { getLifeEvents } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';
import GoalEditor from './GoalEditor';
import { useReturnTo } from '../../useReturnTo';

function GoalPageForClient({ goalId }: { goalId?: string }) {
    const { clientId, currentClient } = useClient();
    const navigate = useNavigate();
    const { scenarioId } = useParams();
    const returnTo = useReturnTo(scenarioId ? `/goals/scenarios/${scenarioId}/events` : '/goals/scenarios');
    const mutation = useMutation();
    const load = useCallback(async () => {
        if (goalId === undefined) return null;
        const goal = (await getLifeEvents(true)).find((row) => row.id === Number(goalId));
        if (!goal) throw new Error('このライフイベントは見つかりません。');
        return goal;
    }, [goalId]);
    const resource = useResource(load);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const identified = currentClient?.id === clientId;
    const leave = () => navigate(returnTo, { replace: true });
    return <section className="mx-auto max-w-3xl space-y-4">
        <h2 className="text-lg font-semibold">{goalId ? `「${resource.data?.name ?? `ライフイベント #${goalId}`}」を編集` : '新しいライフイベント'}</h2>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} />
        {resource.loading && <button type="button" onClick={leave} className={buttonClass}>キャンセル</button>}
        {!resource.loading && !resource.error && <GoalEditor goal={resource.data} scenarioId={scenarioId ? Number(scenarioId) : undefined} currency={currency} busy={!identified || mutation.busy} onCancel={leave}
            onSave={(action) => void mutation.run(action, 'ライフイベントを保存しました。', leave)} />}
        {resource.error && <div className="flex gap-2"><button type="button" onClick={leave} className={buttonClass}>キャンセル</button></div>}
    </section>;
}

export default function GoalPage() {
    const { clientId } = useClient();
    const { goalId } = useParams();
    const { pathname } = useLocation();
    // A client or route change must not reuse another goal's draft.
    return <GoalPageForClient key={`${clientId}:${pathname}`} goalId={goalId} />;
}
