export interface Session {
    id: string;
    created_at: string;
    last_seen_at: string;
    expires_at: string;
    stepped_up_at: string | null;
    stage: string | null;
}
export interface Me { username: string; permissions: string[]; session: Session }
export interface SignInResult {
    stage: 'password_change' | 'mfa_setup' | 'mfa' | null;
    admin: { username: string };
    otpauth_uri?: string;
    manual_entry_key?: string;
    recovery_codes?: string[];
}
export interface Client {
    id: number;
    username: string;
    name: string;
    email: string | null;
    is_active: boolean;
    approval_pending: boolean;
    suspended_reason: string | null;
    must_change_password: boolean;
    locked_until: string | null;
    mfa_enabled: boolean;
    created_at: string;
    transaction_count: number;
    last_transaction_date: string | null;
}
export interface Admin {
    id: number;
    username: string;
    is_active: boolean;
    mfa_enabled: boolean;
    permissions: string[];
    last_login_at: string | null;
}
export interface AuditRow {
    id: number;
    at: string;
    actor: string;
    action: string;
    target_client_id: number | null;
    target_admin_id: number | null;
    result: string;
}
export interface HealthIssue {
    code: string;
    title: string;
    count: number;
    audience: string;
    repairable: boolean;
    items: unknown[];
}
export interface Health { status: string; total_issues: number; repairable_groups: number; issues: HealthIssue[] }
export interface OverviewData {
    clients: Record<'total' | 'active' | 'suspended' | 'pending_approval' | 'locked' | 'without_totp', number>;
    admins: number;
    health?: { clients: { client_id: number; user: number; admin: number }[]; limit: number; checked_clients: number; truncated: boolean };
    recent_audit?: AuditRow[];
}
export interface Setting { value: string | number; default: string | number; updated_at: string | null; updated_by: string | null }
export interface TemporaryPassword { temporary_password: string; id?: number; username?: string }
