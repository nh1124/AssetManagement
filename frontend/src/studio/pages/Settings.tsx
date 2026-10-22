import AccountSettings from './AccountSettings';
import Household from './Household';
import SimulationSettings from './SimulationSettings';
import { useConfirm } from '../components/useConfirm';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { isAxiosError } from 'axios';
import { Help } from '../components/Help';
import TotpSetup from '../components/TotpSetup';
import RecoveryCodes from '../components/RecoveryCodes';
import { useLocation } from 'react-router-dom';
import { exportData, getMfaStatus, importData, regenerateMfaRecoveryCodes, startMfaReplacement, updateClientSettings, verifyMfaReplacement } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { TotpProvisioning } from '../../types';
import { clientToday, formatDateTime, normalizeTimezone, useTimezone } from '../datetime';
import { useLanguage, type Language, type TranslationKey, tr } from '../i18n';
import { useResource } from '../useResource';
import { Field } from './db/Database';
import { buttonClass, inputClass, primaryClass } from './db/forms';

class InvalidBackupError extends Error {}

// Keep messages translatable and never render API validation payloads, which may
// contain the user's password or code. Secrets live only in this mounted screen.
function useSettingsMutation() {
    const { t } = useLanguage();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const inFlight = useRef(false);
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);
    const run = async <T,>(action: () => Promise<T>, confirmation: TranslationKey | (() => string), onSuccess?: (result: T) => void) => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        setError(null);
        setMessage(null);
        try {
            const result = await action();
            if (mounted.current) {
                onSuccess?.(result);
                setMessage(typeof confirmation === 'function' ? confirmation() : t(confirmation));
            }
        } catch (failure: unknown) {
            if (mounted.current) {
                const detail = isAxiosError<{ detail?: unknown }>(failure) ? failure.response?.data?.detail : undefined;
                setError(failure instanceof InvalidBackupError ? t('settings.invalidFile') : typeof detail === 'string' ? detail : t('settings.failed'));
            }
        } finally {
            inFlight.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    return { busy, error, message, run };
}

const COMMON_ZONES = ['UTC', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Singapore', 'Asia/Kolkata', 'Europe/London', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney', 'Pacific/Auckland'];
const sectionClass = 'space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5';

function SettingsForClient() {
    const confirm = useConfirm();
    const { clientId, currentClient, refreshClients } = useClient();
    const { t } = useLanguage();
    const timezone = useTimezone();
    const mfa = useResource(getMfaStatus);
    const openMfa = useLocation().hash === '#mfa';
    useEffect(() => { if (openMfa) document.getElementById('mfa')?.scrollIntoView(); }, [openMfa]);
    const mutation = useSettingsMutation();
    const [savedGeneral, setSavedGeneral] = useState<Record<string, unknown> | null>(null);
    const [currencyEdit, setCurrencyEdit] = useState<string | null>(null);
    const [timezoneEdit, setTimezoneEdit] = useState<string | null>(null);
    const [languageEdit, setLanguageEdit] = useState<Language | null>(null);
    const [file, setFile] = useState<File | null>(null);
    const [householdRevision, setHouseholdRevision] = useState(0);
    const [setup, setSetup] = useState<TotpProvisioning | null>(null);
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
    const hasCredential = Boolean(code.trim());
    const factor = () => /^\d{6}$/.test(code.trim()) ? { code: code.trim() } : { recovery_code: code.trim() };

    const clearCredentials = () => { setCode(''); };
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
        if (mfaDisabled || setup || !hasCredential || recoveryCodes.length) return;
        void mutation.run(() => startMfaReplacement(factor()), () => tr('新しい認証アプリで登録してください。', 'Add this account to your new authenticator app.'), (result) => {
            clearCredentials();
            setRecoveryCodes([]);
            setSetup(result);
        });
    };
    const verifySetup = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (mfaDisabled || !setup || !/^\d{6}$/.test(code.trim())) return;
        void mutation.run(() => verifyMfaReplacement({ code: code.trim() }), () => tr('認証アプリを変更しました。新しい回復コードを保存してください。', 'Authenticator app changed. Save the new recovery codes.'), (result) => {
            localStorage.setItem('finance_access_token', result.access_token);
            clearCredentials();
            setSetup(null);
            setRecoveryCodes(result.recovery_codes);
            mfa.setData((previous) => previous ? { ...previous, enabled: true, recovery_codes_remaining: result.recovery_codes.length } : previous);
            mfa.reload();
        });
    };
    const regenerateCodes = async () => {
        if (mfaDisabled || setup || recoveryCodes.length > 0 || !hasCredential || !(await confirm(tr('現在の回復コードはすべて無効になります。新しいコードを作りますか？', 'All current recovery codes will stop working. Generate new codes?'), tr('再生成する', 'Regenerate')))) return;
        void mutation.run(() => regenerateMfaRecoveryCodes(factor()), () => tr('新しい回復コードを保存してください。', 'Save your new recovery codes.'), (result) => {
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
        {mutation.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{mutation.error}</p>}
        {mutation.message && <p role="status" className="text-sm text-[var(--studio-positive)]">{mutation.message}</p>}
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
            <summary className="cursor-pointer text-sm font-semibold">{tr('多要素認証（MFA）', 'Multi-factor authentication (MFA)')}</summary>
            {mfa.loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込み中…', 'Loading…')}</p>}
            {mfa.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('認証の状態を取得できません。', 'Could not load authentication status.')}</p>}
            <dl className="space-y-2 text-sm">
                <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{tr('状態', 'Status')}</dt><dd>{tr('有効', 'Enabled')}</dd></div>
                {mfa.data && <>
                    <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{tr('回復コード残数', 'Recovery codes remaining')}</dt><dd>{mfa.data.recovery_codes_remaining}</dd></div>
                    {mfa.data.enabled_at && <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{tr('有効化日時', 'Enabled at')}</dt><dd>{formatDateTime(mfa.data.enabled_at, timezone)}</dd></div>}
                    {mfa.data.last_verified_at && <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">{tr('最終認証日時', 'Last verified at')}</dt><dd>{formatDateTime(mfa.data.last_verified_at, timezone)}</dd></div>}
                </>}
            </dl>
            {!recoveryCodes.length && <fieldset disabled={mfaDisabled} className="space-y-4">
                {!setup && <>
                    <div className="flex items-center gap-2"><h3 className="text-sm font-semibold">{tr('認証アプリを替える', 'Change authenticator app')}</h3><Help label={tr('認証アプリ', 'Authenticator app')} text={tr('今の認証アプリのコードか回復コードで確認してから、新しいアプリを登録します。認証アプリはすべてのアカウントで必要です。', 'Verify with your current authenticator code or a recovery code, then register the new app. An authenticator app is required for every account.')} /></div>
                    <Field label={tr('今の認証コード、または回復コード', 'Current authenticator code or recovery code')}><input type="text" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} className={inputClass} /></Field>
                    <div className="flex flex-wrap gap-3">
                        <button type="button" onClick={beginSetup} disabled={mfaDisabled || !hasCredential} className={primaryClass}>{tr('認証アプリを替える', 'Change authenticator app')}</button>
                        <button type="button" onClick={regenerateCodes} disabled={mfaDisabled || !hasCredential} className={buttonClass}>{tr('回復コードを再生成', 'Regenerate recovery codes')}</button>
                    </div>
                </>}
                {setup && <form onSubmit={verifySetup} className="space-y-4 rounded-md border border-[var(--studio-border)] p-4">
                    <div className="flex items-center gap-2"><h3 className="text-sm font-semibold">{tr('新しい認証アプリを設定', 'Set up the new authenticator app')}</h3><Help label={tr('登録方法', 'Setup')} text={tr('新しいアプリでQRコードを読み取るか、手入力用のキーを登録してください。確認が終わるまで、今のアプリを使えます。', 'Scan the QR code in the new app or enter the manual key. Your current app works until verification is complete.')} /></div>
                    <TotpSetup key={setup.otpauth_uri} setup={setup} />
                    <Field label={tr('新しいアプリの6桁のコード', '6-digit code from the new app')}><input required type="text" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} className={inputClass} /></Field>
                    <div className="flex flex-wrap gap-3"><button type="submit" disabled={mfaDisabled || !/^\d{6}$/.test(code.trim())} className={primaryClass}>{tr('確認して変更する', 'Verify and change')}</button><button type="button" onClick={clearSecurity} className={buttonClass}>{tr('キャンセル', 'Cancel')}</button></div>
                </form>}
            </fieldset>}
            {recoveryCodes.length > 0 && <RecoveryCodes codes={recoveryCodes} onContinue={() => setRecoveryCodes([])} />}
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
