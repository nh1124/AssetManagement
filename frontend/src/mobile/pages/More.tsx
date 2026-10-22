import { Bell, ExternalLink, Inbox, LogOut, PiggyBank, Settings, WalletMinimal } from 'lucide-react';
import { useCallback } from 'react';
import { getAiChangeRequests } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { useClient } from '../../context/ClientContext';
import { useNotifications } from '../../studio/notificationContext';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { Badge, List, Row } from '../components/ui';
import { tr } from '../../studio/i18n';

const icon = (Icon: typeof Bell) => <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--studio-accent-soft)] text-[var(--studio-accent)]"><Icon size={17} aria-hidden /></span>;

/** Everything not on the tab bar. */
export default function More() {
    const { currentClient } = useClient();
    const { logout } = useAuth();
    const { items } = useNotifications();
    const load = useCallback(() => getAiChangeRequests({ status: 'pending' }), []);
    const requests = useResource(load);
    const waiting = requests.data?.length ?? 0;
    return <Screen title={tr('メニュー', 'Menu')} back={-1}>
        <div className="flex items-center gap-3 rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--studio-rail)] text-base font-bold text-white">{(currentClient?.name ?? '?').slice(0, 1)}</span>
            <div className="min-w-0"><p className="truncate font-semibold">{currentClient?.name ?? ''}</p>
                <p className="text-xs text-[var(--studio-text-muted)]">{currentClient?.general_settings?.currency || 'JPY'}</p></div>
        </div>
        <List title={tr('お金', 'Money')}>
            <Row to="/accounts" title={<span className="flex items-center gap-3">{icon(WalletMinimal)}{tr('資産と口座', 'Assets and accounts')}</span>} />
            <Row to="/earmarks" title={<span className="flex items-center gap-3">{icon(PiggyBank)}{tr('取り置き', 'Earmarks')}</span>} />
        </List>
        <List title={tr('確認すること', 'To review')}>
            <Row to="/approvals" title={<span className="flex items-center gap-3">{icon(Inbox)}{tr('AI からの変更の承認', 'Approve changes from AI')}</span>} trailing={waiting > 0 ? <Badge tone="warning">{tr(`${waiting}件`, `${waiting}`)}</Badge> : undefined} />
            <Row to="/notifications" title={<span className="flex items-center gap-3">{icon(Bell)}{tr('通知', 'Notifications')}</span>} trailing={items.length > 0 ? <Badge tone="warning">{tr(`${items.length}件`, `${items.length}`)}</Badge> : undefined} />
        </List>
        <List title={tr('その他', 'Other')}>
            <Row to="/settings" title={<span className="flex items-center gap-3">{icon(Settings)}{tr('設定', 'Settings')}</span>} />
            <Row onClick={() => { window.location.href = '/studio'; }} title={<span className="flex items-center gap-3">{icon(ExternalLink)}{tr('PC版（スタジオ）を開く', 'Open the desktop version')}</span>} chevron={false} />
            <Row onClick={logout} title={<span className="flex items-center gap-3 text-[var(--studio-danger)]"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-red-50"><LogOut size={17} aria-hidden /></span>{tr('ログアウト', 'Sign out')}</span>} chevron={false} />
        </List>
        <p className="px-1 text-xs text-[var(--studio-text-muted)]">{tr('シナリオの編集、データベース、レポートなどは PC版で行います。', 'Scenarios, the database, reports and more are on the desktop version.')}</p>
    </Screen>;
}
