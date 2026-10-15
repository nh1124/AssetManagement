import { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { deleteGoal, getCapsules, getGoalCapsules } from '../../../api';
import type { LifeEvent } from '../../../types';
import { useResource } from '../../useResource';
import { Choice, DataTable, Feedback } from '../db/Database';
import { buttonClass, loadAccounts } from '../db/forms';
import { capsuleClaims, claimTotals } from './presentation';

export default function GoalDeletion({ goal, clientName, busy, onDelete }: {
    goal: LifeEvent; clientName: string; busy: boolean;
    onDelete: (action: () => Promise<unknown>) => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const load = useCallback(async () => {
        const [capsules, accounts, allCapsules] = await Promise.all([getGoalCapsules(goal.id), loadAccounts(), getCapsules()]);
        // A funding account may be removed by goal deletion, so cannot receive the return.
        const sourceIds = new Set(allCapsules.filter((row) => row.life_event_id === goal.id).flatMap((row) => (row.funding_sources ?? []).map((source) => source.account_id)));
        return { capsules, accounts: accounts.filter((row) => row.account_type === 'asset' && row.is_active !== false && !sourceIds.has(row.id)) };
    }, [goal.id]);
    const resource = useResource(load);
    const [accountId, setAccountId] = useState<number | null>(null);
    const account = resource.data?.accounts.find((row) => row.id === accountId);
    const needsTransfer = resource.data?.capsules.some((row) => row.claims.some((claim) => claim.amount > 0)) ?? false;
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || resource.loading || resource.error || !resource.data || (needsTransfer && !account)) return;
        const amounts = resource.data.capsules.map((row) => `${row.name}：${capsuleClaims(row)}`).join('\n');
        const returnMessage = needsTransfer && account ? `取り置きの確保額 ${claimTotals(resource.data.capsules)} を口座「${account.name}」に返金します。` : '返金対象額はありません。';
        if (!(await confirm(`「${clientName}」のライフイベント「${goal.name}」を削除します。\n${returnMessage}\n取り置き・規則・マイルストーンも削除します。復元はできません。\n${amounts || '取り置きはありません。'}\n${needsTransfer && account ? `返金先「${account.name}」で` : ''}削除しますか？`, '削除する'))) return;
        onDelete(() => deleteGoal(goal.id, needsTransfer ? account?.id : undefined));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4 rounded-lg border border-[var(--studio-danger)] p-5">
        <p className="text-xs text-[var(--studio-text-muted)]">取り置き・規則・マイルストーンも削除されます。履歴を残して計画を中止したい場合は「中止する」を使ってください。</p>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <DataTable columns={['取り置き', '返金する確保額（通貨別）']}>
            {resource.data.capsules.map((row) => <tr key={row.id}><th scope="row" className="px-5 py-3 font-normal">{row.name}</th><td className="px-5 py-3 tabular-nums">{capsuleClaims(row)}</td></tr>)}
        </DataTable>}
        <fieldset disabled={busy || resource.loading || Boolean(resource.error)} className="space-y-4">
            {needsTransfer && <Choice label="返金先の口座" value={accountId} options={resource.data?.accounts ?? []} required onChange={setAccountId} />}
            {needsTransfer && resource.data && !resource.data.accounts.length && <p className="text-sm text-[var(--studio-danger)]">返金先にできる有効な資産口座がありません。先に口座を作成してください。</p>}
            {account && <p className="text-sm">返金先：{account.name}</p>}
            <div className="flex gap-2"><OverlayFooter><button type="submit" form={formId} disabled={busy || resource.loading || Boolean(resource.error) || (needsTransfer && !account) || busy || !resource.data} className={`${buttonClass} text-[var(--studio-danger)]`}>{needsTransfer ? '返金して削除' : '削除を確認'}</button></OverlayFooter></div>
        </fieldset>
    </form>;
}
