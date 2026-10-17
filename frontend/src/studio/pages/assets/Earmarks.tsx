import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useState } from 'react';
import { deleteCapsule, getCapsules, getLifeEvents } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';
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
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const selectedCapsule = capsules?.find((capsule) => capsule.id === selectedId);
    const [rulesBusy, setRulesBusy] = useState(false);
    const disabled = loading || Boolean(error) || mutation.busy || rulesBusy || !clientName;
    const remove = async (capsule: Capsule) => {
        if (disabled) return;
        const accounts = (capsule.funding_sources ?? []).map((row) => row.account_name || `口座 #${row.account_id}`).join('、');
        if (!(await confirm(`「${clientName}」の取り置き「${capsule.name}」と規則を削除しますか？\n口座${accounts ? `「${accounts}」` : ''}の残高・取引履歴はそのまま残ります。取り置きの帰属は解除されます。`, '削除する'))) return;
        let result: Awaited<ReturnType<typeof deleteCapsule>> | null = null;
        setDeleteResult(null);
        void mutation.run(async () => { result = await deleteCapsule(capsule.id); }, '', () => { setDeleteResult(result); setSelectedId(null); reload(); });
    };

    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <div className="flex gap-2"><button type="button" disabled={disabled || editor !== null || goals.loading || Boolean(goals.error)} onClick={() => { setDeleteResult(null); setEditor({ capsule: null }); }} className={buttonClass}>新しい取り置き</button></div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">取り置きを読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">取り置きを取得できませんでした。{error}</p>}
            <Feedback error={goals.error || mutation.error} message={mutation.message} />
            {deleteResult && <Feedback message={`「${deleteResult.capsule_name || '取り置き'}」と規則${deleteResult.rules_deleted}件を削除しました。${deleteResult.retained_account_id !== null ? `口座「${deleteResult.retained_account_name || '名称未設定'}」（#${deleteResult.retained_account_id}）の残高・履歴は残っています。` : '応答に保持した口座の指定はありません。口座の残高・履歴は変更していません。'}`} />}
            {capsules && (capsules.length ? (
                <DataTable columns={['用途', '確保額', '目標', '進捗']}>
                {capsules.map((capsule) => {
                    const progress = capsule.target_amount > 0 ? capsule.current_balance / capsule.target_amount * 100 : null;
                    return (
                        <tr key={capsule.id} onClick={() => { if (!disabled && editor === null) setSelectedId(capsule.id); }} className={disabled || editor !== null ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                            <th scope="row" className="px-5 py-3 font-medium">
                                <button type="button" disabled={disabled || editor !== null} onClick={(event) => { event.stopPropagation(); setSelectedId(capsule.id); }} aria-haspopup="dialog" aria-label={`${capsule.name}を開く`} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">
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
                        </tr>
                    );
                })}
                </DataTable>
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">取り置きはありません。</p>)}
            {selectedCapsule && <Overlay title={selectedCapsule.name} onClose={() => setSelectedId(null)}>
                <div className="space-y-4">
                    <Feedback error={mutation.error} />
                    <fieldset disabled={disabled || editor !== null} className="min-w-0 space-y-4">
                        <EarmarkAccounts capsuleId={selectedCapsule.id} sources={selectedCapsule.funding_sources ?? []} />
                        <section className="space-y-3">
                            <h3 className="text-sm font-semibold">取り置きの規則</h3>
                            <div className="max-h-64 overflow-y-auto"><CapsuleRules capsule={selectedCapsule} currency={currency} disabled={disabled || editor !== null} onBusy={setRulesBusy} /></div>
                        </section>
                        <section className="space-y-3">
                            <h3 className="text-sm font-semibold">取り崩し履歴</h3>
                            <div className="max-h-64 overflow-y-auto"><Drawdowns capsule={selectedCapsule} currency={currency} onRecorded={reload} /></div>
                        </section>
                    </fieldset>
                    {selectedCapsule.life_event_id ? <p className="text-xs text-[var(--studio-text-muted)]">ライフイベントの中止・削除はライフイベント画面から行えます。</p> : Boolean(selectedCapsule.linked_products?.length) && <p className="text-xs text-[var(--studio-text-muted)]">削除するには物品の紐づけを解除してください。</p>}
                    <OverlayFooter><div className="flex w-full items-center justify-between gap-3">
                        <button type="button" disabled={disabled || editor !== null || Boolean(selectedCapsule.life_event_id) || Boolean(selectedCapsule.linked_products?.length)} onClick={() => remove(selectedCapsule)} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>
                        <button type="button" disabled={disabled || editor !== null} onClick={() => { setDeleteResult(null); setEditor({ capsule: selectedCapsule }); }} className={primaryClass}>編集</button>
                    </div></OverlayFooter>
                </div>
            </Overlay>}
            {editor && <Overlay title={editor.capsule ? `${editor.capsule.name}を編集` : '新しい取り置き'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><EarmarkEditor key={editor.capsule?.id ?? 'new'} capsule={editor.capsule} capsules={capsules ?? []} goals={goals.data ?? []} currency={currency} busy={disabled} onSave={(action) => {
                if (disabled) return;
                setDeleteResult(null);
                void mutation.run(action, '取り置きを保存しました。', () => { setEditor(null); reload(); });
            }} /></Overlay>}
        </section>
    );
}

export default function Earmarks() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Remount drafts and pending mutations when the authenticated client changes.
    return <EarmarksForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
