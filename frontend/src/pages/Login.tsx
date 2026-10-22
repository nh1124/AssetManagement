import { useState } from 'react';
import { isAxiosError } from 'axios';
import { useAuth } from '../context/AuthContext';
import { AlertCircle, Lock, LogIn, Mail, User, UserPlus } from 'lucide-react';
import '../studio/theme.css';
import AppMark from '../studio/components/AppMark';
import { tr } from '../studio/i18n';

const field = 'block w-full min-h-11 rounded-xl border border-[var(--studio-border)] bg-[var(--studio-surface)] pl-10 pr-3 text-base text-[var(--studio-text)] placeholder:text-[var(--studio-text-faint)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
const label = 'mb-1.5 block text-xs font-medium text-[var(--studio-text-muted)]';
const icon = 'pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--studio-text-faint)]';

/** Sign in (with the MFA step when the account has it) or create an account; the studio's look, on phone and PC. */
export default function LoginPage() {
    const [mode, setMode] = useState<'login' | 'register'>('login');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [email, setEmail] = useState('');
    const [mfaToken, setMfaToken] = useState<string | null>(null);
    const [mfaCode, setMfaCode] = useState('');
    const [useRecoveryCode, setUseRecoveryCode] = useState(false);
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const { login, verifyMfaLogin, register } = useAuth();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);
        try {
            if (mfaToken) {
                await verifyMfaLogin({
                    mfa_token: mfaToken,
                    username,
                    ...(useRecoveryCode ? { recovery_code: mfaCode } : { code: mfaCode }),
                });
            } else if (mode === 'login') {
                const result = await login({ username, password });
                if (result.mfa_required && result.mfa_token) {
                    setMfaToken(result.mfa_token);
                    setMfaCode('');
                    return;
                }
            } else {
                await register({ username, password, email: email || undefined });
            }
        } catch (err: unknown) {
            const response = isAxiosError<{ detail?: unknown }>(err) ? err.response : undefined;
            const detail = response?.data?.detail;
            if (typeof detail === 'string') {
                setError(detail);
            } else if (Array.isArray(detail)) {
                setError(detail.map((item: { msg?: string }) => item?.msg || String(item)).join(tr('、', '; ')));
            } else if (!response) {
                setError(tr('サーバーに接続できません。API サーバーが動いているか確認してください。', 'Cannot reach the server. Check that the API server is running.'));
            } else {
                setError(mode === 'login' ? tr('ログインできませんでした。', 'Could not sign in.') : tr('登録できませんでした。', 'Could not create the account.'));
            }
        } finally {
            setIsLoading(false);
        }
    };

    const switchMode = () => {
        setMode(mode === 'login' ? 'register' : 'login');
        setMfaToken(null);
        setMfaCode('');
        setError('');
    };

    return (
        <div className="studio-root flex min-h-dvh items-center justify-center bg-[var(--studio-bg)] p-4 text-[var(--studio-text)]">
            <div className="w-full max-w-sm">
                <div className="mb-8 text-center">
                    <AppMark size={56} className="mx-auto mb-4 rounded-2xl shadow-lg" />
                    <h1 className="text-2xl font-bold tracking-tight">AssetManagement</h1>
                    <p className="mt-1 text-sm text-[var(--studio-text-muted)]">
                        {mfaToken ? tr('認証コードを入力してください', 'Enter your authentication code') : mode === 'login' ? tr('ログインして家計と資産を管理します', 'Sign in to manage your household money and assets') : tr('新しいアカウントを作成します', 'Create a new account')}
                    </p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4 rounded-3xl bg-[var(--studio-surface)] p-6 shadow-[0_10px_40px_rgb(14_42_32/0.08)]">
                    {error && (
                        <div role="alert" className="flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-[var(--studio-danger)]">
                            <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
                            {error}
                        </div>
                    )}

                    {!mfaToken ? (
                        <>
                            <div>
                                <label htmlFor="login-username" className={label}>{tr('ユーザー名', 'Username')}</label>
                                <div className="relative">
                                    <User className={icon} size={16} aria-hidden />
                                    <input id="login-username" type="text" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className={field} required />
                                </div>
                            </div>
                            {mode === 'register' && (
                                <div>
                                    <label htmlFor="login-email" className={label}>{tr('メールアドレス（任意）', 'Email (optional)')}</label>
                                    <div className="relative">
                                        <Mail className={icon} size={16} aria-hidden />
                                        <input id="login-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} placeholder="name@example.com" />
                                    </div>
                                </div>
                            )}
                            <div>
                                <label htmlFor="login-password" className={label}>{tr('パスワード', 'Password')}{mode === 'register' ? tr('（8文字以上）', ' (8 characters or more)') : ''}</label>
                                <div className="relative">
                                    <Lock className={icon} size={16} aria-hidden />
                                    <input id="login-password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password}
                                        onChange={(e) => setPassword(e.target.value)} className={field} required minLength={8} />
                                </div>
                            </div>
                        </>
                    ) : (
                        <div>
                            <label htmlFor="login-mfa" className={label}>{useRecoveryCode ? tr('リカバリーコード', 'Recovery code') : tr('認証アプリの 6 桁のコード', '6-digit code from your authenticator app')}</label>
                            <input id="login-mfa" type="text" inputMode={useRecoveryCode ? 'text' : 'numeric'} autoComplete="one-time-code" value={mfaCode}
                                onChange={(e) => setMfaCode(e.target.value)} placeholder={useRecoveryCode ? 'ABCD-1234' : '123456'} required autoFocus
                                className={`${field} pl-3 text-center font-mono tracking-widest`} />
                            <button type="button" onClick={() => { setUseRecoveryCode(!useRecoveryCode); setMfaCode(''); }}
                                className="mt-2 text-xs font-medium text-[var(--studio-accent)]">
                                {useRecoveryCode ? tr('認証アプリのコードを使う', 'Use an authenticator code') : tr('リカバリーコードを使う', 'Use a recovery code')}
                            </button>
                        </div>
                    )}

                    <button type="submit" disabled={isLoading}
                        className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[var(--studio-accent)] text-sm font-semibold text-white active:opacity-80 disabled:opacity-50">
                        {isLoading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden />
                            : mode === 'login' || mfaToken ? <LogIn size={18} aria-hidden /> : <UserPlus size={18} aria-hidden />}
                        {isLoading ? (mfaToken ? tr('確認しています…', 'Checking…') : mode === 'login' ? tr('ログインしています…', 'Signing in…') : tr('作成しています…', 'Creating…')) : (mfaToken ? tr('確認する', 'Verify') : mode === 'login' ? tr('ログイン', 'Sign in') : tr('アカウントを作成', 'Create account'))}
                    </button>

                    <p className="border-t border-[var(--studio-border)] pt-4 text-center text-xs text-[var(--studio-text-muted)]">
                        {mode === 'login' ? tr('アカウントをお持ちでないとき：', 'No account yet?') : tr('アカウントをお持ちのとき：', 'Have an account?')}
                        <button type="button" onClick={switchMode} className="ml-1 font-semibold text-[var(--studio-accent)]">{mode === 'login' ? tr('新規登録', 'Sign up') : tr('ログイン', 'Sign in')}</button>
                    </p>
                </form>
            </div>
        </div>
    );
}
