import { useState, type FormEvent } from 'react';
import AppMark from '../studio/components/AppMark';
import TotpSetup from '../studio/components/TotpSetup';
import RecoveryCodes from '../studio/components/RecoveryCodes';
import { Help } from '../studio/components/Help';
import { tr } from '../studio/i18n';
import type { AdminApi } from './api';
import type { SignInResult } from './types';
import { Field, Notice, SaveButton } from './ui';
import { useAction } from './hooks';

export default function SignIn({ api, stage, onStage, onSignedIn, notice }: {
    api: AdminApi; stage: SignInResult | null; onStage: (stage: SignInResult | null) => void;
    onSignedIn: () => Promise<void>; notice: string;
}) {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const [code, setCode] = useState('');
    const action = useAction();
    async function accept(result: SignInResult) {
        setPassword(''); setNewPassword(''); setConfirmation(''); setCode('');
        onStage(result);
        if (result.stage === 'mfa_setup' && !result.otpauth_uri) {
            onStage(await api.post<SignInResult>('/session/mfa-setup/start'));
        } else if (result.stage === null && !result.recovery_codes?.length) await onSignedIn();
    }
    async function submit(event: FormEvent) {
        event.preventDefault();
        await action.run(async () => {
            if (!stage) {
                await accept(await api.request<SignInResult>('/session', { method: 'POST', body: { username, password, ...(code.trim() ? { code: code.trim() } : {}) }, authenticate: false }));
            } else if (stage.stage === 'password_change') {
                if (newPassword.length < 12) throw new Error(tr('12文字以上にしてください。', 'Use at least 12 characters.'));
                if (newPassword !== confirmation) throw new Error(tr('パスワードが一致しません。', 'Passwords do not match.'));
                await accept(await api.post<SignInResult>('/session/password', { new_password: newPassword }));
            } else {
                const path = stage.stage === 'mfa_setup' ? '/session/mfa-setup/verify' : '/session/code';
                await accept(await api.post<SignInResult>(path, { code: code.trim() }));
            }
        }, '');
    }
    const title = !stage ? tr('管理者サインイン', 'Administrator sign in') : stage.stage === 'password_change' ? tr('パスワードを変更', 'Change password') : stage.stage === 'mfa_setup' ? tr('認証アプリを設定', 'Set up authenticator') : tr('認証コード', 'Authentication code');
    return <main className="admin-signin"><section className="admin-card">
        <AppMark size={40} /><h1>{title}</h1><Notice message={notice} error={action.error} />
        {stage?.admin.username && <p>{stage.admin.username}</p>}
        {stage?.recovery_codes?.length ? <RecoveryCodes codes={stage.recovery_codes} onContinue={() => void action.run(onSignedIn, '')} />
            : stage?.stage === 'mfa_setup' && !(stage.otpauth_uri && stage.manual_entry_key) ? <button disabled={action.busy} autoFocus onClick={() => void action.run(async () => onStage(await api.post<SignInResult>('/session/mfa-setup/start')), '')}>{tr('設定を開始', 'Start setup')}</button>
                : <form onSubmit={submit}>
                    <fieldset disabled={action.busy}>
                        {!stage && <>
                            <Field id="admin-username" autoFocus label={tr('ユーザー名', 'Username')} autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)} />
                            <Field id="admin-password" label={tr('パスワード', 'Password')} type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} />
                            <Field id="admin-inline-code" label={tr('認証コード（設定済みのとき）', 'Authentication code (if configured)')} inputMode="numeric" autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} />
                        </>}
                        {stage?.stage === 'password_change' && <>
                            <Field id="admin-new-password" autoFocus label={tr('新しいパスワード', 'New password')} type="password" minLength={12} autoComplete="new-password" required value={newPassword} onChange={e => setNewPassword(e.target.value)} help={tr('12文字以上で、今のパスワードと違うものにしてください。', 'Use at least 12 characters, different from your current password.')} />
                            <Field id="admin-confirm-password" label={tr('もう一度入力', 'Confirm password')} type="password" minLength={12} autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)} />
                        </>}
                        {stage?.stage === 'mfa_setup' && stage.otpauth_uri && stage.manual_entry_key && <TotpSetup setup={{ otpauth_uri: stage.otpauth_uri, manual_entry_key: stage.manual_entry_key }} />}
                        {(stage?.stage === 'mfa' || stage?.stage === 'mfa_setup') && <Field id="admin-code" autoFocus label={tr('認証コード', 'Authentication code')} autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" required value={code} onChange={e => setCode(e.target.value)} />}
                        <SaveButton busy={action.busy} label={!stage ? tr('サインイン', 'Sign in') : tr('続ける', 'Continue')} />
                    </fieldset>
                </form>}
        <Help label={tr('管理者サインイン', 'Administrator sign in')} text={tr('管理者用のアカウントで入ります。利用者のアカウントでは入れません。', 'Use an administrator account to sign in. User accounts cannot access this console.')} below />
        {stage && stage.stage !== null && <button disabled={action.busy} onClick={() => onStage(null)}>{tr('最初からやり直す', 'Start again')}</button>}
    </section></main>;
}
