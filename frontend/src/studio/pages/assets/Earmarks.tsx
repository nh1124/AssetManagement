import { useReloadAction } from '../../components/useReloadAction';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { deleteCapsule, getCapsules, getLifeEvents } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';
import EarmarkAccounts from './EarmarkAccounts';
import Drawdowns from './Drawdowns';
import EarmarkEditor from './EarmarkEditor';
import CapsuleRules from './CapsuleRules';

const loadCapsules = (): Promise<Capsule[]> => getCapsules();
const loadGoals = () => getLifeEvents();
const percentFormat = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });

function EarmarksForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const confirm = useConfirm();
    const { data: capsules, loading, error, reload } = useResource(loadCapsules);
    const goals = useResource(loadGoals);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ capsule: Capsule | null } | null>(null);
    const [deleteResult, setDeleteResult] = useState<Awaited<ReturnType<typeof deleteCapsule>> | null>(null);
    const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
    const [rulesBusy, setRulesBusy] = useState(false);
    const disabled = loading || Boolean(error) || mutation.busy || rulesBusy || !clientName;
    const remove = async (capsule: Capsule) => {
        if (disabled) return;
        const accounts = (capsule.funding_sources ?? []).map((row) => row.account_name || `口座 #${row.account_id}`).join('、');
        if (!(await confirm(`「${clientName}」の取り置き「${capsule.name}」と規則を削除しますか？\n口座${accounts ? `「${accounts}」` : ''}の残高・取引履歴はそのまま残ります。取り置きの帰属は解除されます。`, '削除する'))) return;
        let result: Awaited<ReturnType<typeof deleteCapsule>> | null = null;
        setDeleteResult(null);
        void mutation.run(async () => { result = await deleteCapsule(capsule.id); }, '', () => { setDeleteResult(result); reload(); });
    };

    const toggleExpanded = (id: number) => {
        setExpanded((previous) => {
            const next = new Set(previous);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    useReloadAction(() => { reload(); goals.reload(); }, Boolean(loading || mutation.busy || rulesBusy || editor !== null));
    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <div className="flex gap-2"><button type="button" disabled={disabled || editor !== null || goals.loading || Boolean(goals.error)} onClick={() => { setDeleteResult(null); setEditor({ capsule: null }); }} className={buttonClass}>新しい取り置き</button></div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">取り置きを読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">取り置きを取得できませんでした。{error}</p>}
            <Feedback error={goals.error || mutation.error} message={mutation.message} />
            {deleteResult && <Feedback message={`「${deleteResult.capsule_name || '取り置き'}」と規則${deleteResult.rules_deleted}件を削除しました。${deleteResult.retained_account_id !== null ? `口座「${deleteResult.retained_account_name || '名称未設定'}」（#${deleteResult.retained_account_id}）の残高・履歴は残っています。` : '応答に保持した口座の指定はありません。口座の残高・履歴は変更していません。'}`} />}
            {editor && <Overlay title={editor.capsule ? `${editor.capsule.name}を編集` : '新しい取り置き'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><EarmarkEditor key={editor.capsule?.id ?? 'new'} capsule={editor.capsule} capsules={capsules ?? []} goals={goals.data ?? []} currency={currency} busy={disabled} onCancel={() => setEditor(null)} onSave={(action) => {
                if (disabled) return;
                setDeleteResult(null);
                void mutation.run(action, '取り置きを保存しました。', () => { setEditor(null); reload(); });
            }} /></Overlay>}
            {capsules && (capsules.length ? (
                <DataTable columns={['用途', '現在確保している額', '目標', '進捗', '操作']}>
                {capsules.map((capsule) => {
                    const isExpanded = expanded.has(capsule.id);
                    const progress = capsule.target_amount > 0 ? capsule.current_balance / capsule.target_amount * 100 : null;
                    const sources = capsule.funding_sources ?? [];
                    return (
                        <Fragment key={capsule.id}>
                            <tr>
                                <th scope="row" className="px-5 py-3 font-medium">
                                    <button type="button" disabled={mutation.busy || rulesBusy || editor !== null} onClick={() => toggleExpanded(capsule.id)} aria-expanded={isExpanded} aria-controls={`earmark-details-${capsule.id}`} aria-label={`${capsule.name}の詳細`} className="flex items-center gap-2 rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">
                                        {isExpanded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
                                        {capsule.name}
                                    </button>
                                </th>
                                <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatCurrency(capsule.current_balance, currency)}</td>
                                <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatCurrency(capsule.target_amount, currency)}</td>
                                <td className="min-w-36 px-5 py-3">
                                    {progress === null ? <span className="text-xs text-[var(--studio-text-muted)]">目標未設定</span> : (
                                        <div className="space-y-1">
                                            <span className="text-xs tabular-nums text-[var(--studio-text-muted)]">{percentFormat.format(progress)}%</span>
                                            <div role="progressbar" aria-label={`${capsule.name}の進捗`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.max(0, Math.min(100, progress))} aria-valuetext={`${percentFormat.format(progress)}%`} className="h-1.5 overflow-hidden rounded-full bg-[var(--studio-accent-soft)]">
                                                <div className="h-full rounded-full bg-[var(--studio-positive)]" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
                                            </div>
                                        </div>
                                    )}
                                </td>
                                <td className="px-5 py-3"><div className="flex gap-2 whitespace-nowrap">
                                    <button type="button" disabled={disabled || editor !== null} onClick={() => { setDeleteResult(null); setEditor({ capsule }); }} className={buttonClass}>編集</button>
                                    <button type="button" disabled={disabled || editor !== null || Boolean(capsule.life_event_id) || Boolean(capsule.linked_products?.length)} onClick={() => remove(capsule)} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>
                                </div>{capsule.life_event_id ? <p className="mt-2 text-xs text-[var(--studio-text-muted)]">ゴールの中止・削除はゴール画面から行えます。</p> : Boolean(capsule.linked_products?.length) && <p className="mt-2 text-xs text-[var(--studio-text-muted)]">削除するには物品の紐づけを解除してください。</p>}</td>
                            </tr>
                            {isExpanded && (
                                <tr id={`earmark-details-${capsule.id}`} className="bg-[var(--studio-bg)]">
                                    <td colSpan={5} className="px-5 py-4"><fieldset disabled={!clientName || loading || Boolean(error) || mutation.busy || rulesBusy || editor !== null} className="min-w-0">
                                        <p className="mb-3 text-xs text-[var(--studio-text-muted)]">月額積立：{formatCurrency(capsule.monthly_contribution, currency)} ／ 資金源：{sources.length}口座</p>
                                        <EarmarkAccounts capsuleId={capsule.id} sources={sources} />
                                        <details className="mt-3"><summary className="cursor-pointer text-sm text-[var(--studio-accent)]">取り置きの規則</summary>
                                        <CapsuleRules capsule={capsule} currency={currency} disabled={disabled || editor !== null} onBusy={setRulesBusy} />
                                        </details>
                                        <details className="mt-3"><summary className="cursor-pointer text-sm text-[var(--studio-accent)]">取り崩し履歴</summary>
                                        <Drawdowns capsule={capsule} currency={currency} onRecorded={reload} />
                                        </details>
                                        </fieldset>
                                    </td>
                                </tr>
                            )}
                        </Fragment>
                    );
                })}
                </DataTable>
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">取り置きはありません。</p>)}
        </section>
    );
}

export default function Earmarks() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Remount drafts and pending mutations when the authenticated client changes.
    return <EarmarksForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
