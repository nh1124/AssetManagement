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
import { tr } from '../../studio/i18n';

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
    return <Screen title={tr('取り置き', 'Earmarks')} back={-1}>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!resource.data && !resource.error && <Skeleton lines={4} />}
        {resource.data && <>
            <div className="rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <p className="text-xs text-[var(--studio-text-muted)]">{tr('確保額の合計', 'Total set aside')}</p>
                <Money value={held} currency={currency} className="text-2xl font-bold" />
                <p className="mt-1 text-xs text-[var(--studio-text-muted)]">{tr('取り置きは口座の中で用途を決めて確保するお金です（口座からは動きません）。', 'Earmarks are money set aside for a purpose inside an account (it does not leave the account).')}</p>
            </div>
            {capsules.length ? <div className="space-y-2">{capsules.map((capsule) => <button key={capsule.id} type="button" onClick={() => setOpened(capsule)}
                className={`w-full space-y-2 rounded-2xl bg-[var(--studio-surface)] p-4 text-left shadow-[var(--mobile-shadow)] active:bg-[var(--studio-accent-soft)] ${focusRing}`}>
                <div className="flex items-center justify-between gap-2">
                    <p className="flex min-w-0 items-center gap-1.5 text-sm font-semibold"><span className="truncate">{capsule.name}</span>{capsule.is_goal && <Badge tone="accent">{tr('ゴール', 'Goal')}</Badge>}</p>
                    <span className="shrink-0 text-xs text-[var(--studio-text-muted)]">{tr('月', 'Monthly')} {formatCurrency(capsule.monthly_contribution ?? 0, currency)}</span>
                </div>
                <ProgressBar label={tr(`${capsule.name}の確保`, `${capsule.name} set aside`)} value={capsule.current_balance ?? 0} max={capsule.target_amount ?? 0} tone="positive" />
                <p className="text-xs tabular-nums text-[var(--studio-text-muted)]">{formatCurrency(capsule.current_balance ?? 0, currency)} / {formatCurrency(capsule.target_amount ?? 0, currency)}{tr(`（${share(capsule)}%）`, ` (${share(capsule)}%)`)}</p>
            </button>)}</div> : <Empty icon={<PiggyBank size={28} aria-hidden />} title={tr('取り置きはありません', 'No earmarks')} body={tr('PC版のデータベースで作れます。', 'Create them in the desktop database.')} />}
        </>}
        {opened && <Sheet title={opened.name} onClose={() => setOpened(null)}>
            <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">{tr('確保額', 'Set aside')}</p><Money value={opened.current_balance ?? 0} currency={currency} className="text-lg font-bold" /></div>
                    <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">{tr('目標', 'Target')}</p><Money value={opened.target_amount ?? 0} currency={currency} className="text-lg font-bold" /></div>
                </div>
                {(opened.funding_sources?.length ?? 0) > 0 && <List title={tr('資金元の口座', 'Funding accounts')}>
                    {opened.funding_sources?.map((source) => <Row key={source.id ?? source.account_id} title={source.account_name ?? `#${source.account_id}`}
                        trailing={<span className="text-xs text-[var(--studio-text-muted)]">{tr('目標', 'Target')} {formatCurrency(source.target_amount ?? 0, currency)}</span>} />)}
                </List>}
                <p className="text-xs text-[var(--studio-text-muted)]">{tr('確保・使用の記録と規則は PC版で行います。', 'Record setting aside and spending, and edit rules, on the desktop.')}</p>
            </div>
        </Sheet>}
    </Screen>;
}
