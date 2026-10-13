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
    const returnTo = useReturnTo('/goals');
    const mutation = useMutation();
    const load = useCallback(async () => {
        if (goalId === undefined) return null;
        const goal = (await getLifeEvents(true)).find((row) => row.id === Number(goalId));
        if (!goal) throw new Error('このゴールは見つかりません。');
        return goal;
    }, [goalId]);
    const resource = useResource(load);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const identified = currentClient?.id === clientId;
    const leave = () => navigate(returnTo, { replace: true });
    return <section className="mx-auto max-w-3xl space-y-4">
        <h2 className="text-lg font-semibold">{goalId ? `「${resource.data?.name ?? `ゴール #${goalId}`}」を編集` : '新しいゴール'}</h2>
        <p className="text-xs text-[var(--studio-text-muted)]">対象：{identified ? currentClient.name : 'クライアントを確認中…'} ／ {currency}</p>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} />
        {resource.loading && <button type="button" onClick={leave} className={buttonClass}>キャンセル</button>}
        {!resource.loading && !resource.error && <GoalEditor goal={resource.data} currency={currency} busy={!identified || mutation.busy} onCancel={leave}
            onSave={(action) => void mutation.run(action, 'ゴールを保存しました。', leave)} />}
        {resource.error && <div className="flex gap-2"><button type="button" onClick={resource.reload} className={buttonClass}>再読み込み</button><button type="button" onClick={leave} className={buttonClass}>キャンセル</button></div>}
    </section>;
}

export default function GoalPage() {
    const { clientId } = useClient();
    const { goalId } = useParams();
    const { pathname } = useLocation();
    // A client or route change must not reuse another goal's draft.
    return <GoalPageForClient key={`${clientId}:${pathname}`} goalId={goalId} />;
}
