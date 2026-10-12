import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { getCapsules } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useAssetData } from './useAssetData';

const loadCapsules = (): Promise<Capsule[]> => getCapsules();
const percentFormat = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });

export default function Earmarks() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const { data: capsules, loading, error, reload } = useAssetData(loadCapsules);
    const [expanded, setExpanded] = useState<Set<number>>(() => new Set());

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
                    <p className="mt-1 text-xs text-[var(--studio-text-muted)]">用途を展開すると、口座ごとの資金計画を確認できます。</p>
                </div>
                <button type="button" onClick={reload} disabled={loading} className="rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40">再読み込み</button>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">取り置きを読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">取り置きを取得できませんでした。{error}</p>}
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
                                                <button type="button" onClick={() => toggleExpanded(capsule.id)} aria-expanded={isExpanded} aria-controls={`funding-plan-${capsule.id}`} aria-label={`${capsule.name}の資金計画`} className="flex items-center gap-2 rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">
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
