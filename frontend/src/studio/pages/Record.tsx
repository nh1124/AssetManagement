import { useReloadAction } from '../components/useReloadAction';
import { useClient } from '../../context/ClientContext';
import { useCallback, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getTransaction } from '../../api';
import { useResource } from '../useResource';
import { useReturnTo } from '../useReturnTo';
import { Feedback } from './db/Database';
import { buttonClass } from './db/forms';
import RecordForm from './RecordForm';

function TransactionEditor({ transactionId }: { transactionId: string }) {
    const navigate = useNavigate();
    const returnTo = useReturnTo('/ledger');
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);
    const load = useCallback(async () => {
        if (!/^\d+$/.test(transactionId)) throw new Error('この取引は見つかりません。');
        return getTransaction(Number(transactionId));
    }, [transactionId]);
    const resource = useResource(load);
    const leave = () => navigate(returnTo, { replace: true });
    useReloadAction(resource.reload, false, Boolean(resource.error));
    return <section className="space-y-4">
        {(resource.loading || resource.error) && <h2 className="text-lg font-semibold">取引 #{transactionId}を編集</h2>}
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.loading && <button type="button" onClick={leave} className={buttonClass}>キャンセル</button>}
        {resource.data && !resource.loading && !resource.error && <RecordForm existing={resource.data} onSaved={leave} onCancel={leave} />}
        {resource.error && <div className="flex gap-2"><button type="button" onClick={leave} className={buttonClass}>キャンセル</button></div>}
    </section>;
}

export default function Record() {
    const { clientId } = useClient();
    const { transactionId } = useParams();
    return transactionId ? <TransactionEditor key={`${clientId}:${transactionId}`} transactionId={transactionId} /> : <RecordForm key={clientId} />;
}
