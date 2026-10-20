import { Bell, Bot, ExternalLink, LogOut, PiggyBank, Settings, Wallet } from 'lucide-react';
import { useCallback } from 'react';
import { getAiChangeRequests } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { useClient } from '../../context/ClientContext';
import { useNotifications } from '../../studio/notificationContext';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { Badge, List, Row } from '../components/ui';

const icon = (Icon: typeof Bell) => <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--studio-accent-soft)] text-[var(--studio-accent)]"><Icon size={17} aria-hidden /></span>;

/** Everything not on the tab bar. */
export default function More() {
    const { currentClient } = useClient();
    const { logout } = useAuth();
    const { items } = useNotifications();
    const load = useCallback(() => getAiChangeRequests({ status: 'pending' }), []);
    const requests = useResource(load);
    const waiting = requests.data?.length ?? 0;
    return <Screen title="メニュー" back={-1}>
        <div className="flex items-center gap-3 rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--studio-rail)] text-base font-bold text-white">{(currentClient?.name ?? '?').slice(0, 1)}</span>
            <div className="min-w-0"><p className="truncate font-semibold">{currentClient?.name ?? ''}</p>
                <p className="text-xs text-[var(--studio-text-muted)]">{currentClient?.general_settings?.currency || 'JPY'}</p></div>
        </div>
        <List title="お金">
            <Row to="/accounts" title={<span className="flex items-center gap-3">{icon(Wallet)}資産と口座</span>} />
            <Row to="/earmarks" title={<span className="flex items-center gap-3">{icon(PiggyBank)}取り置き</span>} />
        </List>
        <List title="確認すること">
            <Row to="/approvals" title={<span className="flex items-center gap-3">{icon(Bot)}AI からの変更の承認</span>} trailing={waiting > 0 ? <Badge tone="warning">{waiting}件</Badge> : undefined} />
            <Row to="/notifications" title={<span className="flex items-center gap-3">{icon(Bell)}通知</span>} trailing={items.length > 0 ? <Badge tone="warning">{items.length}件</Badge> : undefined} />
        </List>
        <List title="その他">
            <Row to="/settings" title={<span className="flex items-center gap-3">{icon(Settings)}設定</span>} />
            <Row onClick={() => { window.location.href = '/studio'; }} title={<span className="flex items-center gap-3">{icon(ExternalLink)}PC版（スタジオ）を開く</span>} chevron={false} />
            <Row onClick={logout} title={<span className="flex items-center gap-3 text-[var(--studio-danger)]"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-red-50"><LogOut size={17} aria-hidden /></span>ログアウト</span>} chevron={false} />
        </List>
        <p className="px-1 text-xs text-[var(--studio-text-muted)]">シナリオの編集、データベース、レポートなどは PC版で行います。</p>
    </Screen>;
}
