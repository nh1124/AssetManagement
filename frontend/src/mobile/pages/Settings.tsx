import { ExternalLink, LogOut } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useClient } from '../../context/ClientContext';
import { getMfaStatus } from '../../api';
import { useTimezone } from '../../studio/datetime';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { dangerButton, List, Row, secondaryButton } from '../components/ui';

/** What the account is set to; changing it is done on the studio. */
export default function Settings() {
    const { currentClient } = useClient();
    const { user, logout } = useAuth();
    const timezone = useTimezone();
    const mfa = useResource(getMfaStatus);
    return <Screen title="設定" back={-1}>
        <List title="アカウント">
            <Row title="名前" trailing={<span className="text-[var(--studio-text-muted)]">{currentClient?.name ?? user?.name ?? ''}</span>} />
            <Row title="通貨" trailing={<span className="text-[var(--studio-text-muted)]">{currentClient?.general_settings?.currency || 'JPY'}</span>} />
            <Row title="タイムゾーン" trailing={<span className="text-[var(--studio-text-muted)]">{timezone}</span>} />
            <Row title="二段階認証（MFA）" trailing={<span className="text-[var(--studio-text-muted)]">{mfa.data ? (mfa.data.enabled ? '有効' : '無効') : '—'}</span>} />
        </List>
        <p className="px-1 text-xs text-[var(--studio-text-muted)]">設定の変更、AI の権限、データの書き出しは PC版の設定で行います。</p>
        <a href="/studio/settings" className={`${secondaryButton} w-full`}>PC版の設定を開く<ExternalLink size={14} aria-hidden /></a>
        <button type="button" onClick={logout} className={`${dangerButton} w-full`}><LogOut size={16} aria-hidden />ログアウト</button>
    </Screen>;
}
