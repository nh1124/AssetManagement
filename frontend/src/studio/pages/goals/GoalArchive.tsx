import { useCallback, useId, useState, type FormEvent } from 'react';
import { archiveGoal, getGoalCapsules } from '../../../api';
import type { GoalCapsuleAction, LifeEvent } from '../../../types';
import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useResource } from '../../useResource';
import { Choice, DataTable, Feedback } from '../db/Database';
import { buttonClass, loadAccounts } from '../db/forms';
import { capsuleClaims, claimTotals } from './presentation';

const ACTIONS: Array<{ value: GoalCapsuleAction; label: string }> = [
    { value: 'keep', label: '取り置きはそのまま' },
    { value: 'stop_rules', label: '取り置きへの自動確保を止める' },
    { value: 'detach', label: 'ライフイベントとの紐づけを解除する（取り置きは残す）' },
    { value: 'release', label: '取り置きを崩して口座へ戻す' },
];

export default function GoalArchive({ goal, clientName, busy, error, onArchive, onCancel }: {
    goal: LifeEvent; clientName: string; busy: boolean; error: string;
    onArchive: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const load = useCallback(async () => {
        const [capsules, accounts] = await Promise.all([getGoalCapsules(goal.id), loadAccounts()]);
        return { capsules, accounts: accounts.filter((row) => row.account_type === 'asset' && row.is_active !== false) };
    }, [goal.id]);
    const resource = useResource(load);
    const [action, setAction] = useState<GoalCapsuleAction>('keep');
    const [accountId, setAccountId] = useState<number | null>(null);
    const account = resource.data?.accounts.find((row) => row.id === accountId);
    const locked = busy || resource.loading || Boolean(resource.error) || !resource.data;
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (locked || !resource.data || (action === 'release' && !account)) return;
        const decision = action;
        const destination = decision === 'release' ? accountId : null;
        const detail = decision === 'release' ? `口座「${account?.name}」へ ${claimTotals(resource.data.capsules)} を戻します。` : ACTIONS.find((row) => row.value === decision)?.label;
        if (!(await confirm(`「${clientName}」のライフイベント「${goal.name}」をアーカイブします。\n${detail}\nライフイベントを戻しても、解除した紐づけは戻らず、停止した規則は停止したまま、戻したお金は戻したままです。`, 'アーカイブする'))) return;
        onArchive(() => archiveGoal(goal.id, { capsule_action: decision, transfer_account_id: destination }));
    };
    return <Overlay title={`「${goal.name}」をアーカイブ`} busy={busy} onClose={onCancel}>
        <form id={formId} onSubmit={submit} className="space-y-4">
            <Feedback loading={resource.loading} error={resource.error || error} />
            {resource.data && <DataTable columns={['取り置き', '確保額（通貨別）']}>
                {resource.data.capsules.length ? resource.data.capsules.map((capsule) => <tr key={capsule.id}><th scope="row" className="px-5 py-3 font-medium">{capsule.name}</th><td className="px-5 py-3 tabular-nums">{capsuleClaims(capsule)}</td></tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">取り置きはありません。</td></tr>}
            </DataTable>}
            <fieldset disabled={locked} className="space-y-3">
                <legend className="mb-3 text-sm font-semibold">取り置きのお金と自動確保</legend>
                {ACTIONS.map((row) => <label key={row.value} className="flex items-center gap-2 text-sm"><input type="radio" name="capsule_action" value={row.value} checked={action === row.value} onChange={() => setAction(row.value)} />{row.label}</label>)}
                {action === 'keep' && <p className="text-xs text-[var(--studio-text-muted)]">確保済みのお金を残し、自動確保も続けます。</p>}
                {action === 'stop_rules' && <p className="text-xs text-[var(--studio-text-muted)]">すべての自動確保規則を無効にします。確保済みのお金はそのままです。規則は手動で再開できます。</p>}
                {action === 'detach' && <p className="text-xs text-[var(--studio-text-muted)]">確保済みのお金と自動確保規則を残し、このライフイベントとの紐づけだけを解除します。独立した取り置きとして続きます。通貨の換算やお金の移動はありません。</p>}
                {action === 'release' && <>
                    <Choice label="戻す先の口座" value={accountId} options={resource.data?.accounts ?? []} required onChange={setAccountId} />
                    <p className="text-sm">戻す先：{account?.name ?? '未選択'} ／ 合計：{resource.data ? claimTotals(resource.data.capsules) : '—'}</p>
                    <p className="text-xs text-[var(--studio-text-muted)]">自動確保規則は続きます。口座が同じ場合は、口座残高を変えずに取り置きの帰属を解除します。クライアント通貨以外の確保額がある場合は返金できません。紐づけを解除するか、取り置きからその通貨の口座へ取り崩してください。</p>
                    {resource.data && !resource.data.accounts.length && <p className="text-sm text-[var(--studio-danger)]">有効な資産口座を先に作成してください。</p>}
                </>}
                <p className="text-sm text-[var(--studio-text-muted)]">ライフイベントの復元は、取り置きの判断を取り消しません。解除した紐づけは戻らず、停止した規則は停止したまま、口座へ戻したお金は戻したままです。</p>
                <div className="flex gap-2"><OverlayFooter><button type="submit" form={formId} disabled={locked || (action === 'release' && !account)} className={buttonClass}>アーカイブを確認</button></OverlayFooter></div>
            </fieldset>
        </form>
    </Overlay>;
}
