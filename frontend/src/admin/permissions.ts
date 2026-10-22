import { tr } from '../studio/i18n';
export const permissions = ['accounts.read', 'accounts.manage', 'accounts.credentials', 'accounts.export', 'accounts.delete', 'health.read', 'health.repair', 'audit.read', 'settings.manage', 'ops.read', 'ops.run', 'admins.manage'] as const;
export function permissionLabel(permission: string): string {
    const labels: Record<string, string> = {
        'accounts.read': tr('アカウントを見る', 'View accounts'), 'accounts.manage': tr('アカウントを管理', 'Manage accounts'),
        'accounts.credentials': tr('認証情報を再設定', 'Reset credentials'), 'accounts.export': tr('データを書き出す', 'Export data'),
        'accounts.delete': tr('アカウントを削除', 'Delete accounts'), 'health.read': tr('データを確認', 'Check data health'),
        'health.repair': tr('データを修復', 'Repair data'), 'audit.read': tr('監査ログを見る', 'Read audit'),
        'settings.manage': tr('設定を変更', 'Manage settings'), 'ops.read': tr('運用情報を見る', 'View operations'),
        'ops.run': tr('運用操作を実行', 'Run operations'), 'admins.manage': tr('管理者を管理', 'Manage administrators'),
    };
    return labels[permission] ?? permission;
}
export const presets: Record<string, readonly string[]> = {
    owner: permissions,
    support: ['accounts.read', 'accounts.manage', 'health.read', 'audit.read'],
    viewer: permissions.filter(p => p.endsWith('.read')),
};
