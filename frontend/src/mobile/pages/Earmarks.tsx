import { useCallback, useState } from 'react';
import { PiggyBank } from 'lucide-react';
import { getCapsules } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { Capsule } from '../../types';
import { formatCurrency } from '../../utils/currency';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import Sheet from '../components/Sheet';
import { Badge, Empty, ErrorNote, focusRing, List, Money, ProgressBar, Row, Skeleton } from '../components/ui';

const share = (capsule: Capsule) => capsule.target_amount > 0 ? Math.min(100, Math.round((capsule.current_balance ?? 0) / capsule.target_amount * 100)) : 0;

/** Money set aside in accounts for a purpose: what each holds against its target. */
export default function Earmarks() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const load = useCallback(() => getCapsules(), []);
    const resource = useResource(load);
    const [opened, setOpened] = useState<Capsule | null>(null);
    const capsules = resource.data ?? [];
    const held = capsules.reduce((sum, capsule) => sum + (capsule.current_balance ?? 0), 0);
    return <Screen title="取り置き" back={-1}>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!resource.data && !resource.error && <Skeleton lines={4} />}
        {resource.data && <>
            <div className="rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <p className="text-xs text-[var(--studio-text-muted)]">確保額の合計</p>
                <Money value={held} currency={currency} className="text-2xl font-bold" />
                <p className="mt-1 text-xs text-[var(--studio-text-muted)]">取り置きは口座の中で用途を決めて確保するお金です（口座からは動きません）。</p>
            </div>
            {capsules.length ? <div className="space-y-2">{capsules.map((capsule) => <button key={capsule.id} type="button" onClick={() => setOpened(capsule)}
                className={`w-full space-y-2 rounded-2xl bg-[var(--studio-surface)] p-4 text-left shadow-[var(--mobile-shadow)] active:bg-[var(--studio-accent-soft)] ${focusRing}`}>
                <div className="flex items-center justify-between gap-2">
                    <p className="flex min-w-0 items-center gap-1.5 text-sm font-semibold"><span className="truncate">{capsule.name}</span>{capsule.is_goal && <Badge tone="accent">ゴール</Badge>}</p>
                    <span className="shrink-0 text-xs text-[var(--studio-text-muted)]">月 {formatCurrency(capsule.monthly_contribution ?? 0, currency)}</span>
                </div>
                <ProgressBar label={`${capsule.name}の確保`} value={capsule.current_balance ?? 0} max={capsule.target_amount ?? 0} tone="positive" />
                <p className="text-xs tabular-nums text-[var(--studio-text-muted)]">{formatCurrency(capsule.current_balance ?? 0, currency)} / {formatCurrency(capsule.target_amount ?? 0, currency)}（{share(capsule)}%）</p>
            </button>)}</div> : <Empty icon={<PiggyBank size={28} aria-hidden />} title="取り置きはありません" body="PC版のデータベースで作れます。" />}
        </>}
        {opened && <Sheet title={opened.name} onClose={() => setOpened(null)}>
            <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">確保額</p><Money value={opened.current_balance ?? 0} currency={currency} className="text-lg font-bold" /></div>
                    <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">目標</p><Money value={opened.target_amount ?? 0} currency={currency} className="text-lg font-bold" /></div>
                </div>
                {(opened.funding_sources?.length ?? 0) > 0 && <List title="資金元の口座">
                    {opened.funding_sources?.map((source) => <Row key={source.id ?? source.account_id} title={source.account_name ?? `#${source.account_id}`}
                        trailing={<span className="text-xs text-[var(--studio-text-muted)]">目標 {formatCurrency(source.target_amount ?? 0, currency)}</span>} />)}
                </List>}
                <p className="text-xs text-[var(--studio-text-muted)]">確保・使用の記録と規則は PC版で行います。</p>
            </div>
        </Sheet>}
    </Screen>;
}
