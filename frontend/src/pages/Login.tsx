import { useRef, useState, type FormEvent } from 'react';
import { isAxiosError } from 'axios';
import { useAuth } from '../context/AuthContext';
import { changeSignInPassword, startEnrollment, verifyEnrollment, verifyMfaLogin } from '../api';
import type { AccessResult, EnrollmentResult, SignInStep, TotpProvisioning } from '../types';
import { AlertCircle, Lock, LogIn, Mail, User, UserPlus } from 'lucide-react';
import '../studio/theme.css';
import AppMark from '../studio/components/AppMark';
import { Help } from '../studio/components/Help';
import TotpSetup from '../studio/components/TotpSetup';
import RecoveryCodes from '../studio/components/RecoveryCodes';
import { tr } from '../studio/i18n';

const field = 'block w-full min-h-11 rounded-xl border border-[var(--studio-border)] bg-[var(--studio-surface)] pl-10 pr-3 text-base text-[var(--studio-text)] placeholder:text-[var(--studio-text-faint)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
const label = 'mb-1.5 block text-xs font-medium text-[var(--studio-text-muted)]';
const icon = 'pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--studio-text-faint)]';

/** The same staged sign-in on phone and PC; no access token is stored before completion. */
export default function LoginPage() {
    const [mode, setMode] = useState<'login' | 'register'>('login');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [email, setEmail] = useState('');
    const [step, setStep] = useState<SignInStep | null>(null);
    const [setup, setSetup] = useState<TotpProvisioning | null>(null);
    const [recovery, setRecovery] = useState<EnrollmentResult | null>(null);
    const [newPassword, setNewPassword] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const [mfaCode, setMfaCode] = useState('');
    const [useRecoveryCode, setUseRecoveryCode] = useState(false);
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const inFlight = useRef(false);
    const { login, register, completeSignIn } = useAuth();
    const mismatch = Boolean(confirmation) && newPassword !== confirmation;

    const reset = () => {
        setMode('login');
        setStep(null);
        setSetup(null);
        setRecovery(null);
        setPassword('');
        setNewPassword('');
        setConfirmation('');
        setMfaCode('');
        setUseRecoveryCode(false);
        setError('');
    };
    const showError = (err: unknown, atStep: boolean) => {
        const response = isAxiosError<{ detail?: unknown }>(err) ? err.response : undefined;
        const detail = response?.data?.detail;
        // Invalid MFA factors also use 401; keep the step so the user can retry.
        const invalidFactor = step?.next_step === 'mfa' && (detail === 'Invalid MFA code' || detail === '認証コードが正しくありません。');
        if (atStep && response?.status === 401 && !invalidFactor) {
            reset();
            setError(tr('時間切れです。もう一度サインインしてください。', 'This took too long. Please sign in again.'));
        } else if (typeof detail === 'string') {
            setError(detail);
        } else if (Array.isArray(detail)) {
            setError(detail.map((item: { msg?: string }) => item?.msg || String(item)).join(tr('、', '; ')));
        } else if (!response) {
            setError(tr('サーバーに接続できません。', 'Cannot reach the server.'));
        } else {
            setError(tr('サインインできませんでした。', 'Could not sign in.'));
        }
    };
    const finish = (result: AccessResult) => completeSignIn(result.access_token, { id: result.client_id, name: result.name, username });
    const enterStep = async (result: SignInStep) => {
        setStep(result);
        setPassword('');
        setNewPassword('');
        setConfirmation('');
        setMfaCode('');
        setUseRecoveryCode(false);
        setSetup(null);
        // Start once per transition, outside an effect (also safe under StrictMode).
        if (result.next_step === 'mfa_setup') {
            try { setSetup(await startEnrollment(result.step_token)); }
            catch (err) { showError(err, true); }
        }
    };
    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        if (inFlight.current || recovery) return;
        setError('');
        inFlight.current = true;
        setIsLoading(true);
        try {
            if (!step) {
                await enterStep(mode === 'login' ? await login({ username, password }) : await register({ username, password, email: email || undefined }));
            } else if (step.next_step === 'password_change') {
                if (newPassword.length < 8 || newPassword !== confirmation) {
                    setError(tr('8文字以上の同じパスワードを入力してください。', 'Enter matching passwords of at least 8 characters.'));
                    return;
                }
                await enterStep(await changeSignInPassword({ step_token: step.step_token, new_password: newPassword }));
            } else if (step.next_step === 'mfa_setup' && setup) {
                const result = await verifyEnrollment({ step_token: step.step_token, code: mfaCode.trim() });
                setRecovery(result);
                setSetup(null);
                setStep(null);
                setMfaCode('');
            } else if (step.next_step === 'mfa') {
                finish(await verifyMfaLogin({ mfa_token: step.mfa_token ?? step.step_token,
                    ...(useRecoveryCode ? { recovery_code: mfaCode.trim() } : { code: mfaCode.trim() }) }));
            }
        } catch (err: unknown) { showError(err, step !== null); }
        finally {
            inFlight.current = false;
            setIsLoading(false);
        }
    };
    const heading = recovery ? tr('回復コードを保存してください', 'Save your recovery codes')
        : step?.next_step === 'password_change' ? tr('パスワードを変更してください', 'Change your password')
        : step?.next_step === 'mfa_setup' ? tr('認証アプリを設定します', 'Set up your authenticator app')
        : step?.next_step === 'mfa' ? tr('認証コードを入力してください', 'Enter your authentication code')
        : mode === 'login' ? tr('ログイン', 'Sign in') : tr('アカウントを作成', 'Create account');

    return <div className="studio-root flex min-h-dvh items-center justify-center bg-[var(--studio-bg)] p-4 text-[var(--studio-text)]">
        <div className="w-full max-w-sm">
            <div className="mb-8 text-center">
                <AppMark size={56} className="mx-auto mb-4 rounded-2xl shadow-lg" />
                <h1 className="text-2xl font-bold tracking-tight">{tr('AssetManagement', 'AssetManagement')}</h1>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4 rounded-3xl bg-[var(--studio-surface)] p-6 shadow-[0_10px_40px_rgb(14_42_32/0.08)]">
                <div className="flex items-center gap-2"><h2 className="text-base font-semibold">{heading}</h2>
                    {step?.next_step === 'mfa_setup' && <Help below label={heading} text={tr('Google Authenticator や 1Password などの認証アプリを使います。すべてのアカウントで必要です。', 'Use an authenticator app such as Google Authenticator or 1Password. This is required for every account.')} />}
                </div>
                {error && <div role="alert" className="flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-[var(--studio-danger)]"><AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />{error}</div>}
                {recovery ? <RecoveryCodes codes={recovery.recovery_codes} onContinue={() => finish(recovery)} continueLabel={tr('サインインする', 'Finish sign-in')} /> : <>
                    <fieldset disabled={isLoading} className="space-y-4">
                        {!step && <>
                            <div><label htmlFor="login-username" className={label}>{tr('ユーザー名', 'Username')}</label><div className="relative">
                                <User className={icon} size={16} aria-hidden /><input id="login-username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className={field} required />
                            </div></div>
                            {mode === 'register' && <div><label htmlFor="login-email" className={label}>{tr('メールアドレス（任意）', 'Email (optional)')}</label><div className="relative">
                                <Mail className={icon} size={16} aria-hidden /><input id="login-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
                            </div></div>}
                            <div><label htmlFor="login-password" className={label}>{mode === 'register' ? tr('パスワード（8文字以上）', 'Password (8 characters or more)') : tr('パスワード', 'Password')}</label><div className="relative">
                                <Lock className={icon} size={16} aria-hidden /><input id="login-password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={(e) => setPassword(e.target.value)} className={field} required minLength={mode === 'register' ? 8 : undefined} />
                            </div></div>
                        </>}
                        {step?.next_step === 'password_change' && <>
                            <div><label htmlFor="new-password" className={label}>{tr('新しいパスワード（8文字以上）', 'New password (8 characters or more)')}</label><input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className={`${field} pl-3`} minLength={8} required /></div>
                            <div><label htmlFor="confirm-password" className={label}>{tr('新しいパスワード（確認）', 'Confirm new password')}</label><input id="confirm-password" type="password" autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} className={`${field} pl-3`} minLength={8} required /></div>
                            {mismatch && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('パスワードが一致しません。', 'Passwords do not match.')}</p>}
                        </>}
                        {step?.next_step === 'mfa_setup' && (setup ? <TotpSetup key={setup.otpauth_uri} setup={setup} /> : isLoading && <p role="status" className="text-sm">{tr('設定を準備中…', 'Preparing setup…')}</p>)}
                        {(step?.next_step === 'mfa' || (step?.next_step === 'mfa_setup' && setup)) && <div>
                            <label htmlFor="login-mfa" className={label}>{useRecoveryCode ? tr('回復コード', 'Recovery code') : tr('認証アプリの6桁のコード', '6-digit code from your authenticator app')}</label>
                            <input id="login-mfa" inputMode={useRecoveryCode ? 'text' : 'numeric'} autoComplete="one-time-code" value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} required pattern={useRecoveryCode ? undefined : '[0-9]{6}'} maxLength={useRecoveryCode ? undefined : 6} className={`${field} pl-3 text-center font-mono tracking-widest`} />
                            {step.next_step === 'mfa' && <button type="button" onClick={() => { setUseRecoveryCode(!useRecoveryCode); setMfaCode(''); }} className="mt-2 text-xs font-medium text-[var(--studio-accent)]">{useRecoveryCode ? tr('認証アプリのコードを使う', 'Use an authenticator code') : tr('回復コードを使う', 'Use a recovery code')}</button>}
                        </div>}
                        <button type="submit" disabled={isLoading || mismatch || (step?.next_step === 'mfa_setup' && !setup)} className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[var(--studio-accent)] text-sm font-semibold text-white active:opacity-80 disabled:opacity-50">
                            {mode === 'login' || step ? <LogIn size={18} aria-hidden /> : <UserPlus size={18} aria-hidden />}
                            {isLoading ? tr('確認中…', 'Checking…') : step ? tr('次へ', 'Continue') : mode === 'login' ? tr('ログイン', 'Sign in') : tr('アカウントを作成', 'Create account')}
                        </button>
                        {step && <button type="button" onClick={reset} className="text-xs text-[var(--studio-accent)]">{tr('最初に戻る', 'Start again')}</button>}
                        {!step && <div className="border-t border-[var(--studio-border)] pt-4 text-center text-xs"><button type="button" onClick={() => { reset(); setMode(mode === 'login' ? 'register' : 'login'); }} className="font-semibold text-[var(--studio-accent)]">{mode === 'login' ? tr('新規登録', 'Sign up') : tr('ログインに戻る', 'Back to sign in')}</button></div>}
                    </fieldset>
                </>}
            </form>
        </div>
    </div>;
}
