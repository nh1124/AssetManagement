import { ExternalLink, LogOut } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useClient } from '../../context/ClientContext';
import { getMfaStatus } from '../../api';
import { useTimezone } from '../../studio/datetime';
import { useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { dangerButton, List, Row, secondaryButton } from '../components/ui';
import { tr } from '../../studio/i18n';

/** What the account is set to; changing it is done on the studio. */
export default function Settings() {
    const { currentClient } = useClient();
    const { user, logout } = useAuth();
    const timezone = useTimezone();
    const mfa = useResource(getMfaStatus);
    return <Screen title={tr('設定', 'Settings')} back={-1}>
        <List title={tr('アカウント', 'Account')}>
            <Row title={tr('名前', 'Name')} trailing={<span className="text-[var(--studio-text-muted)]">{currentClient?.name ?? user?.name ?? ''}</span>} />
            <Row title={tr('通貨', 'Currency')} trailing={<span className="text-[var(--studio-text-muted)]">{currentClient?.general_settings?.currency || 'JPY'}</span>} />
            <Row title={tr('タイムゾーン', 'Timezone')} trailing={<span className="text-[var(--studio-text-muted)]">{timezone}</span>} />
            <Row title={tr('言語', 'Language')} trailing={<span className="text-[var(--studio-text-muted)]">{tr('日本語', 'English')}</span>} />
            <Row title={tr('二段階認証（MFA）', 'Two-step verification (MFA)')} trailing={<span className="text-[var(--studio-text-muted)]">{mfa.data ? (mfa.data.enabled ? tr('有効', 'On') : tr('無効', 'Off')) : '—'}</span>} />
        </List>
        <p className="px-1 text-xs text-[var(--studio-text-muted)]">{tr('設定の変更、AI の権限、データの書き出しは PC版の設定で行います。', 'Change settings, AI permissions and data export in the desktop settings.')}</p>
        <a href="/studio/settings" className={`${secondaryButton} w-full`}>{tr('PC版の設定を開く', 'Open desktop settings')}<ExternalLink size={14} aria-hidden /></a>
        <button type="button" onClick={logout} className={`${dangerButton} w-full`}><LogOut size={16} aria-hidden />{tr('ログアウト', 'Sign out')}</button>
    </Screen>;
}
