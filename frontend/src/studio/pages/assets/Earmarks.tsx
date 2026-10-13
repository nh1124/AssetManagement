import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { getCapsules } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource as useAssetData } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import FundingPlanEditor, { FundingPlanSummary } from './FundingPlanEditor';
import Drawdowns from './Drawdowns';

const loadCapsules = (): Promise<Capsule[]> => getCapsules();
const percentFormat = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });

function EarmarksForClient({ currency }: { currency: string }) {
    const { data: capsules, loading, error, reload, setData } = useAssetData(loadCapsules);
    const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
    const [editingId, setEditingId] = useState<number | null>(null);
    const [message, setMessage] = useState('');

    const toggleExpanded = (id: number) => {
        setExpanded((previous) => {
            const next = new Set(previous);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold">取り置き</h2>
                    <p className="mt-1 text-xs text-[var(--studio-text-muted)]">用途を展開すると、口座ごとの資金計画を確認・編集できます。</p>
                </div>
                <button type="button" onClick={() => { setMessage(''); reload(); }} disabled={loading || editingId !== null} className={buttonClass}>再読み込み</button>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">取り置きを読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">取り置きを取得できませんでした。{error}</p>}
            <Feedback message={message} />
            {capsules && (capsules.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading}>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr>
                                <th scope="col" className="px-5 py-3 font-medium">用途</th>
                                <th scope="col" className="whitespace-nowrap px-5 py-3 text-right font-medium">現在確保している額</th>
                                <th scope="col" className="px-5 py-3 text-right font-medium">目標</th>
                                <th scope="col" className="px-5 py-3 font-medium">進捗</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {capsules.map((capsule) => {
                                const isExpanded = expanded.has(capsule.id);
                                // The journal claim belongs to the capsule; sources expose only plans.
                                const progress = capsule.target_amount > 0 ? capsule.current_balance / capsule.target_amount * 100 : null;
                                const sources = [...(capsule.funding_sources ?? [])].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
                                return (
                                    <Fragment key={capsule.id}>
                                        <tr>
                                            <th scope="row" className="px-5 py-3 font-medium">
                                                <button type="button" disabled={editingId === capsule.id} onClick={() => toggleExpanded(capsule.id)} aria-expanded={isExpanded} aria-controls={`funding-plan-${capsule.id}`} aria-label={`${capsule.name}の資金計画`} className="flex items-center gap-2 rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">
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
                                        </tr>
                                        {isExpanded && (
                                            <tr id={`funding-plan-${capsule.id}`} className="bg-[var(--studio-bg)]">
                                                <td colSpan={4} className="px-5 py-4">
                                                    {editingId === capsule.id ? <FundingPlanEditor
                                                        capsuleId={capsule.id} sources={sources} target={capsule.target_amount} currency={currency}
                                                        onCancel={() => setEditingId(null)}
                                                        onSaved={(savedSources) => {
                                                            // Use the authoritative saved plan without inventing per-account claims.
                                                            setData((previous) => previous?.map((row) => row.id === capsule.id ? { ...row, funding_sources: savedSources } : row) ?? null);
                                                            setEditingId(null);
                                                            setMessage(`「${capsule.name}」の資金計画を保存しました。`);
                                                        }}
                                                    /> : <div className="space-y-3">
                                                        {sources.length ? (
                                                            <div className="space-y-3">
                                                                <p className="text-xs text-[var(--studio-text-muted)]">資金計画（口座ごとの計画額）</p>
                                                                <table className="w-full text-left text-xs">
                                                                    <caption className="sr-only">{capsule.name}の資金計画</caption>
                                                                    <thead className="text-[var(--studio-text-muted)]"><tr><th scope="col" className="pb-2 font-medium">口座</th><th scope="col" className="pb-2 text-right font-medium">計画額</th><th scope="col" className="pb-2 text-right font-medium">持ち分上限</th></tr></thead>
                                                                    <tbody className="divide-y divide-[var(--studio-border)]">
                                                                        {sources.map((source) => (
                                                                            <tr key={source.id}>
                                                                                <th scope="row" className="py-2 font-normal">{source.account_name ?? '名称未設定の口座'}</th>
                                                                                <td className="whitespace-nowrap py-2 text-right tabular-nums">{formatCurrency(source.target_amount, currency)}</td>
                                                                                <td className="whitespace-nowrap py-2 text-right tabular-nums">{source.max_share_bp === null ? '上限なし' : `${percentFormat.format(source.max_share_bp / 100)}%`}</td>
                                                                            </tr>
                                                                        ))}
                                                                    </tbody>
                                                                </table>
                                                            </div>
                                                        ) : <p className="text-sm text-[var(--studio-text-muted)]">資金計画はまだありません。</p>}
                                                        <FundingPlanSummary total={sources.reduce((sum, source) => sum + source.target_amount, 0)} target={capsule.target_amount} currency={currency} />
                                                        <button type="button" disabled={loading || Boolean(error) || editingId !== null} onClick={() => { setMessage(''); setEditingId(capsule.id); }} className={buttonClass}>資金計画を編集</button>
                                                    </div>}
                                                    <Drawdowns capsule={capsule} currency={currency} onRecorded={reload} />
                                                </td>
                                            </tr>
                                        )}
                                    </Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">取り置きはありません。</p>)}
        </section>
    );
}

export default function Earmarks() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Remount drafts and pending mutations when the authenticated client changes.
    return <EarmarksForClient key={clientId} currency={currency} />;
}
