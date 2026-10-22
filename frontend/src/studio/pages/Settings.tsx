import AccountSettings from './AccountSettings';
import Household from './Household';
import SimulationSettings from './SimulationSettings';
import { useConfirm } from '../components/useConfirm';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import QRCode from 'qrcode';
import { useLocation } from 'react-router-dom';
import { disableMfa, exportData, getMfaStatus, importData, regenerateMfaRecoveryCodes, startMfaSetup, updateClientSettings, verifyMfaSetup } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { MfaSetupStart } from '../../types';
import { clientToday, formatDateTime, normalizeTimezone, useTimezone } from '../datetime';
import { useLanguage, type Language, type TranslationKey, tr } from '../i18n';
import { useResource } from '../useResource';
import { Field } from './db/Database';
import { buttonClass, inputClass, primaryClass } from './db/forms';

class InvalidBackupError extends Error {}

// Keep messages translatable and never render API validation payloads, which may
// contain the user's password or code. Secrets live only in this mounted screen.
function useSettingsMutation() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<TranslationKey | null>(null);
    const [message, setMessage] = useState<TranslationKey | null>(null);
    const inFlight = useRef(false);
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);
    const run = async <T,>(action: () => Promise<T>, confirmation: TranslationKey, onSuccess?: (result: T) => void) => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        setError(null);
        setMessage(null);
        try {
            const result = await action();
            if (mounted.current) {
                onSuccess?.(result);
                setMessage(confirmation);
            }
        } catch (failure: unknown) {
            if (mounted.current) setError(failure instanceof InvalidBackupError ? 'settings.invalidFile' : 'settings.failed');
        } finally {
            inFlight.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    return { busy, error, message, run };
}

function SetupQr({ setup }: { setup: MfaSetupStart }) {
    const { t } = useLanguage();
    const load = useCallback(() => QRCode.toDataURL(setup.otpauth_uri, { width: 208, margin: 2, errorCorrectionLevel: 'M' }), [setup.otpauth_uri]);
    const qr = useResource(load);
    return qr.data ? <img src={qr.data} alt={t('mfa.qrAlt')} width={208} height={208} />
        : <p role={qr.error ? 'alert' : 'status'} className="text-xs text-[var(--studio-text-muted)]">{t(qr.error ? 'mfa.qrFailed' : 'mfa.qrLoading')}</p>;
}

const COMMON_ZONES = ['UTC', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Singapore', 'Asia/Kolkata', 'Europe/London', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney', 'Pacific/Auckland'];
const sectionClass = 'space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5';

function SettingsForClient() {
    const confirm = useConfirm();
    const { clientId, currentClient, refreshClients } = useClient();
    const { t } = useLanguage();
    const timezone = useTimezone();
    const mfa = useResource(getMfaStatus);
    // The approval screen links here (設定 › MFA) when an approval needs MFA.
    const openMfa = useLocation().hash === '#mfa';
    useEffect(() => { if (openMfa) document.getElementById('mfa')?.scrollIntoView(); }, [openMfa]);
    const mutation = useSettingsMutation();
    const [savedGeneral, setSavedGeneral] = useState<Record<string, unknown> | null>(null);
    const [currencyEdit, setCurrencyEdit] = useState<string | null>(null);
    const [timezoneEdit, setTimezoneEdit] = useState<string | null>(null);
    const [languageEdit, setLanguageEdit] = useState<Language | null>(null);
    const [file, setFile] = useState<File | null>(null);
    const [householdRevision, setHouseholdRevision] = useState(0);
    const [setup, setSetup] = useState<MfaSetupStart | null>(null);
    const [password, setPassword] = useState('');
    const [code, setCode] = useState('');
    const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
    const general: Record<string, unknown> = savedGeneral ?? currentClient?.general_settings ?? {};
    const storedCurrency = typeof general.currency === 'string' ? general.currency : 'JPY';
    const storedTimezone = normalizeTimezone(general.timezone);
    const storedLanguage = general.language === 'en' ? 'en' : 'ja';
    const currency = currencyEdit ?? storedCurrency;
    const selectedTimezone = timezoneEdit ?? storedTimezone;
    const language = languageEdit ?? storedLanguage;
    const [browserZone] = useState(() => normalizeTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone));
    const zones = [...new Set([...COMMON_ZONES, browserZone, storedTimezone])];
    const identified = currentClient?.id === clientId;
    const disabled = mutation.busy || !identified;
    const changed = currency !== storedCurrency || selectedTimezone !== storedTimezone || language !== storedLanguage;
    const mfaDisabled = disabled || mfa.loading || Boolean(mfa.error) || !mfa.data;
    const hasCredential = Boolean(password || code.trim());

    const clearCredentials = () => { setPassword(''); setCode(''); };
    const clearSecurity = () => { clearCredentials(); setSetup(null); setRecoveryCodes([]); };
    const save = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || !changed) return;
        // Settings are replaced as a whole object; retain unrelated preferences.
        const next = { ...general, currency, timezone: selectedTimezone, language };
        void mutation.run(() => updateClientSettings(clientId, next), 'settings.saved', () => {
            setSavedGeneral(next);
            setCurrencyEdit(null);
            setTimezoneEdit(null);
            setLanguageEdit(null);
            void refreshClients();
        });
    };
    const beginSetup = () => {
        if (mfaDisabled || mfa.data?.enabled || setup || !password) return;
        void mutation.run(() => startMfaSetup({ current_password: password }), 'mfa.started', (result) => {
            clearCredentials();
            setRecoveryCodes([]);
            setSetup(result);
        });
    };
    const verifySetup = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (mfaDisabled || !setup || !code.trim()) return;
        void mutation.run(() => verifyMfaSetup({ code: code.trim() }), 'mfa.setupDone', (result) => {
            clearCredentials();
            setSetup(null);
            setRecoveryCodes(result.recovery_codes);
            mfa.setData((previous) => previous ? { ...previous, enabled: true, recovery_codes_remaining: result.recovery_codes.length } : previous);
            mfa.reload();
        });
    };
    const turnOffMfa = async () => {
        if (mfaDisabled || !mfa.data?.enabled || !hasCredential || !(await confirm(t('mfa.disableConfirm'), tr('解除する', 'Disable')))) return;
        void mutation.run(() => disableMfa({ current_password: password || undefined, code: code.trim() || undefined }), 'mfa.disabledDone', () => {
            clearSecurity();
            mfa.setData((previous) => previous ? { ...previous, enabled: false, recovery_codes_remaining: 0 } : previous);
            mfa.reload();
        });
    };
    const regenerateCodes = async () => {
        if (mfaDisabled || !mfa.data?.enabled || !hasCredential || !(await confirm(t('mfa.regenerateConfirm'), tr('再生成する', 'Regenerate')))) return;
        void mutation.run(() => regenerateMfaRecoveryCodes({ current_password: password || undefined, code: code.trim() || undefined }), 'mfa.regenerated', (result) => {
            clearCredentials();
            setRecoveryCodes(result.recovery_codes);
            mfa.setData((previous) => previous ? { ...previous, recovery_codes_remaining: result.recovery_codes.length } : previous);
            mfa.reload();
        });
    };
    const download = () => {
        if (disabled) return;
        void mutation.run(async () => {
            const snapshot: unknown = await exportData();
            const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }));
            const link = document.createElement('a');
            link.href = url;
            link.download = `asset-management-client-${clientId}-${clientToday(timezone)}.json`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        }, 'settings.exported');
    };
    const upload = async () => {
        if (disabled || !file) return;
        if (!(await confirm(t('settings.importConfirm', { file: file.name, name: currentClient?.name ?? '', id: clientId }), tr('読み込む', 'Import')))) return;
        void mutation.run(async () => {
            let payload: unknown;
            try { payload = JSON.parse(await file.text()); }
            catch { throw new InvalidBackupError(); }
            if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new InvalidBackupError();
            await importData(payload);
        }, 'settings.imported', () => {
            setFile(null);
            setHouseholdRevision((value) => value + 1);
            setSavedGeneral(null);
            setCurrencyEdit(null);
            setTimezoneEdit(null);
            setLanguageEdit(null);
            clearSecurity();
            void refreshClients();
            mfa.reload();
        });
    };
    return <section className="space-y-6">
        <div><p className="mt-1 text-xs text-[var(--studio-text-muted)]">{identified ? t('settings.client', { name: currentClient.name, id: clientId }) : t('settings.identifying')}</p></div>
        {mutation.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{t(mutation.error)}</p>}
        {mutation.message && <p role="status" className="text-sm text-[var(--studio-positive)]">{t(mutation.message)}</p>}
        <details open className={sectionClass}>
            <summary className="cursor-pointer text-sm font-semibold">{t('settings.preferences')}</summary>
            <form onSubmit={save}>
            <fieldset disabled={disabled} className="space-y-4">
                <div className="grid gap-4 md:grid-cols-3">
                    <Field label={t('settings.currency')}><input required pattern="[A-Z]{3}" maxLength={3} value={currency} onChange={(event) => setCurrencyEdit(event.target.value.toUpperCase())} className={inputClass} list="studio-settings-currencies" /><datalist id="studio-settings-currencies">{['JPY', 'USD', 'EUR', 'GBP', 'CNY', 'KRW'].map((entry) => <option key={entry} value={entry} />)}</datalist></Field>
                    <Field label={t('settings.timezone')}><select value={selectedTimezone} onChange={(event) => setTimezoneEdit(event.target.value)} className={inputClass}>{zones.map((zone) => <option key={zone} value={zone}>{zone === browserZone ? t('settings.browserZone', { zone }) : zone}</option>)}</select></Field>
                    <Field label={t('settings.language')}><select value={language} onChange={(event) => setLanguageEdit(event.target.value as Language)} className={inputClass}><option value="ja">日本語</option><option value="en">English</option></select></Field>
                </div>
                <p className="text-xs text-[var(--studio-text-muted)]">{t('settings.timezoneScope')}</p>
                <p className="text-xs text-[var(--studio-text-muted)]">{t('settings.languageScope')}</p>
                <button type="submit" disabled={disabled || !changed} className={primaryClass}>{t(mutation.busy ? 'common.busy' : 'settings.save')}</button>
            </fieldset>
            </form>
        </details>
        <AccountSettings sectionClass={sectionClass} />
        <details id="mfa" open={openMfa} className={sectionClass}>
            <summary className="cursor-pointer text-sm font-semibold">{t('mfa.title')}</summary>
            {mfa.loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{t('common.loading')}</p>}
            {mfa.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{t('settings.mfaLoadFailed')}</p>}
            {mfa.data && <dl className="space-y-2 text-sm">
                <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{t('mfa.status')}</dt><dd>{t(mfa.data.enabled ? 'mfa.enabled' : 'mfa.disabled')}</dd></div>
                {mfa.data.enabled && <>
                    <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{t('mfa.remaining')}</dt><dd>{mfa.data.recovery_codes_remaining}</dd></div>
                    {mfa.data.enabled_at && <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{t('mfa.enabledAt')}</dt><dd>{formatDateTime(mfa.data.enabled_at, timezone)}</dd></div>}
                    {mfa.data.last_verified_at && <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{t('mfa.verifiedAt')}</dt><dd>{formatDateTime(mfa.data.last_verified_at, timezone)}</dd></div>}
                </>}
            </dl>}
            <p className="text-xs text-[var(--studio-text-muted)]">{t('mfa.credentials')}</p>
            <fieldset disabled={mfaDisabled} className="space-y-4">
                {!setup && <div className="grid gap-4 md:grid-cols-2">
                    <Field label={t('mfa.password')}><input type="password" autoComplete="off" value={password} onChange={(event) => setPassword(event.target.value)} className={inputClass} /></Field>
                    {mfa.data?.enabled && <Field label={t('mfa.code')}><input type="text" autoComplete="off" inputMode="numeric" value={code} onChange={(event) => setCode(event.target.value)} className={inputClass} /></Field>}
                </div>}
                {setup && <form onSubmit={verifySetup} className="space-y-4 rounded-md border border-[var(--studio-border)] p-4">
                    <p className="text-sm">{t('mfa.setupHelp')}</p>
                    <SetupQr key={setup.otpauth_uri} setup={setup} />
                    <div className="space-y-2 text-sm"><p className="text-[var(--studio-text-muted)]">{t('mfa.manualKey')}</p><code className="block select-all break-all font-mono">{setup.manual_entry_key}</code></div>
                    <Field label={t('mfa.code')}><input required type="text" autoComplete="off" inputMode="numeric" value={code} onChange={(event) => setCode(event.target.value)} className={inputClass} /></Field>
                    <div className="flex flex-wrap gap-3"><button type="submit" disabled={mfaDisabled || !code.trim()} className={primaryClass}>{t(mutation.busy ? 'common.busy' : 'mfa.verify')}</button><button type="button" onClick={clearSecurity} className={buttonClass}>{t('common.cancel')}</button></div>
                </form>}
                {!mfa.data?.enabled && !setup && <button type="button" onClick={beginSetup} disabled={mfaDisabled || !password} className={primaryClass}>{t(mutation.busy ? 'common.busy' : 'mfa.start')}</button>}
                {mfa.data?.enabled && <div className="flex flex-wrap gap-3">
                    <button type="button" onClick={regenerateCodes} disabled={mfaDisabled || !hasCredential} className={buttonClass}>{t('mfa.regenerate')}</button>
                    <button type="button" onClick={turnOffMfa} disabled={mfaDisabled || !hasCredential} className={`${buttonClass} text-[var(--studio-danger)]`}>{t('mfa.disable')}</button>
                </div>}
            </fieldset>
            {recoveryCodes.length > 0 && <div className="space-y-3 rounded-md border border-[var(--studio-border)] bg-[var(--studio-accent-soft)] p-4">
                <h4 className="text-sm font-semibold">{t('mfa.recoveryTitle')}</h4>
                <p role="alert" className="text-sm">{t('mfa.recoveryWarning')}</p>
                <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{recoveryCodes.map((entry) => <li key={entry}><code className="select-all font-mono text-sm">{entry}</code></li>)}</ul>
                <div className="flex flex-wrap gap-3"><button type="button" disabled={mutation.busy} onClick={() => void mutation.run(() => navigator.clipboard.writeText(recoveryCodes.join('\n')), 'mfa.copied')} className={buttonClass}>{t('mfa.copy')}</button><button type="button" disabled={mutation.busy} onClick={() => setRecoveryCodes([])} className={buttonClass}>{t('mfa.dismiss')}</button></div>
            </div>}
        </details>
        <Household key={householdRevision} disabled={disabled} clientName={identified ? currentClient.name : undefined} />
        <SimulationSettings key={`simulation-${householdRevision}`} disabled={disabled} sectionClass={sectionClass} />
        <details className={sectionClass}>
            <summary className="cursor-pointer text-sm font-semibold">{t('settings.transfer')}</summary>
            <button type="button" disabled={disabled} onClick={download} className={buttonClass}>{t('settings.export')}</button>
            <div className="space-y-3 border-t border-[var(--studio-border)] pt-4">
                <Field label={t('settings.file')}><input type="file" accept=".json,application/json" disabled={disabled} onChange={(event) => { setFile(event.target.files?.[0] ?? null); event.target.value = ''; }} className={inputClass} /></Field>
                {file && <p className="text-sm">{t('settings.selectedFile', { name: file.name })}</p>}
                <p className="text-xs text-[var(--studio-text-muted)]">{t('settings.importScope')}</p>
                <button type="button" disabled={disabled || !file} onClick={upload} className={buttonClass}>{t(mutation.busy ? 'common.busy' : 'settings.import')}</button>
            </div>
        </details>
    </section>;
}

export default function Settings() {
    const { clientId } = useClient();
    // Switching clients discards selected files, edits and all MFA secrets.
    return <SettingsForClient key={clientId} />;
}
