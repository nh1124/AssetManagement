import { useState, type FormEvent } from 'react';
import { isAxiosError } from 'axios';
import { getMe, updateProfile } from '../../api';
import { useClient } from '../../context/ClientContext';
import { useLanguage, type TranslationKey } from '../i18n';
import { useResource } from '../useResource';
import { Field } from './db/Database';
import { inputClass, primaryClass } from './db/forms';

interface Me { id: number; name: string; email?: string | null }

// Statuses, not server messages: a validation payload may echo a password.
function failure(error: unknown): TranslationKey {
    const status = isAxiosError(error) ? error.response?.status : undefined;
    return status === 403 ? 'account.wrongPassword' : status === 409 ? 'account.taken' : status === 422 ? 'account.invalid' : 'settings.failed';
}

/** The signed-in account: name, email and password. */
export default function AccountSettings({ sectionClass }: { sectionClass: string }) {
    const { t } = useLanguage();
    const { refreshClients } = useClient();
    const me = useResource<Me>(getMe);
    const [name, setName] = useState<string | null>(null);
    const [email, setEmail] = useState<string | null>(null);
    const [password, setPassword] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const [current, setCurrent] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<TranslationKey | null>(null);
    const [message, setMessage] = useState<TranslationKey | null>(null);
    const nameValue = name ?? me.data?.name ?? '';
    const emailValue = email ?? me.data?.email ?? '';
    const emailChanged = email !== null && email.trim() !== (me.data?.email ?? '');
    const needsCurrent = emailChanged || Boolean(password);
    const mismatch = Boolean(password) && password !== confirmation;
    const run = async (action: () => Promise<unknown>, done: TranslationKey) => {
        setBusy(true);
        setError(null);
        setMessage(null);
        try {
            await action();
            setMessage(done);
            setName(null);
            setEmail(null);
            setPassword('');
            setConfirmation('');
            setCurrent('');
            me.reload();
            void refreshClients();
        } catch (caught: unknown) {
            setError(failure(caught));
        } finally {
            setBusy(false);
        }
    };
    const saveProfile = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || mismatch || (needsCurrent && !current)) return;
        void run(() => updateProfile({
            name: name !== null ? name.trim() : undefined,
            email: emailChanged ? emailValue.trim() : undefined,
            password: password || undefined,
            current_password: needsCurrent ? current : undefined,
        }), 'account.saved');
    };
    return <details className={sectionClass}>
        <summary className="cursor-pointer text-sm font-semibold">{t('account.title')}</summary>
        {me.loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{t('common.loading')}</p>}
        {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{t(error)}</p>}
        {message && <p role="status" className="text-sm text-[var(--studio-positive)]">{t(message)}</p>}
        {me.data && <>
            <form onSubmit={saveProfile}>
                <fieldset disabled={busy} className="space-y-4">
                    <div className="grid gap-4 md:grid-cols-2">
                        <Field label={t('account.name')}><input required value={nameValue} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
                        <Field label={t('account.email')}><input type="email" value={emailValue} onChange={(event) => setEmail(event.target.value)} autoComplete="email" className={inputClass} /></Field>
                        <Field label={t('account.newPassword')}><input type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" className={inputClass} /></Field>
                        <Field label={t('account.confirmPassword')}><input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" className={inputClass} /></Field>
                        {needsCurrent && <Field label={t('mfa.password')}><input type="password" required value={current} onChange={(event) => setCurrent(event.target.value)} autoComplete="current-password" className={inputClass} /></Field>}
                    </div>
                    {mismatch && <p role="alert" className="text-xs text-[var(--studio-danger)]">{t('account.mismatch')}</p>}
                    <p className="text-xs text-[var(--studio-text-muted)]">{t('account.help')}</p>
                    <button type="submit" disabled={busy || mismatch || (needsCurrent && !current)} className={primaryClass}>{t(busy ? 'common.busy' : 'account.save')}</button>
                </fieldset>
            </form>
        </>}
    </details>;
}
