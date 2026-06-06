import { type ChangeEvent, useEffect, useRef, useState } from 'react';
import {
    Activity,
    AlertTriangle,
    CheckCircle2,
    Database,
    Download,
    Eye,
    EyeOff,
    Key,
    PlusCircle,
    RefreshCw,
    Save,
    ShieldCheck,
    Upload,
    User,
    Wrench,
} from 'lucide-react';
import SplitView from '../components/SplitView';
import { useClient } from '../context/ClientContext';
import { useAuth } from '../context/AuthContext';
import {
    checkDataHealth,
    disableMfa,
    exportData,
    getMfaStatus,
    importData,
    regenerateMfaRecoveryCodes,
    repairDataHealth,
    startMfaSetup,
    updateClientKey,
    updateClientSettings,
    updateProfile,
    verifyMfaSetup,
} from '../api';
import { useToast } from '../components/Toast';
import type { DataHealthResult, MfaSetupStart, MfaStatus } from '../types';

type SettingsTab = 'security' | 'preferences' | 'transfer' | 'health';

export default function SettingsPage() {
    const { user } = useAuth();
    const { clientId, currentClient, refreshClients } = useClient();
    const { showToast } = useToast();

    const [settings, setSettings] = useState({
        name: user?.name || '',
        email: user?.email || '',
        newPassword: '',
        currency: 'JPY',
        language: 'ja',
        geminiApiKey: '',
    });
    const [activeTab, setActiveTab] = useState<SettingsTab>('security');
    const [showApiKey, setShowApiKey] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const [saved, setSaved] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [isExporting, setIsExporting] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const [health, setHealth] = useState<DataHealthResult | null>(null);
    const [isCheckingHealth, setIsCheckingHealth] = useState(false);
    const [isRepairingHealth, setIsRepairingHealth] = useState(false);
    const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
    const [mfaSetup, setMfaSetup] = useState<MfaSetupStart | null>(null);
    const [mfaPassword, setMfaPassword] = useState('');
    const [mfaCode, setMfaCode] = useState('');
    const [mfaRecoveryCodes, setMfaRecoveryCodes] = useState<string[]>([]);
    const [isMfaBusy, setIsMfaBusy] = useState(false);
    const importInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        const general = currentClient?.general_settings || user?.general_settings || {};
        setSettings((prev) => ({
            ...prev,
            name: user?.name || prev.name,
            email: user?.email || prev.email,
            currency: general.currency || 'JPY',
            language: general.language || 'ja',
        }));
    }, [currentClient?.id, user?.id]);

    useEffect(() => {
        refreshMfaStatus();
    }, [user?.id]);

    const refreshMfaStatus = async () => {
        try {
            setMfaStatus(await getMfaStatus());
        } catch {
            setMfaStatus(null);
        }
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await updateProfile({
                name: settings.name,
                email: settings.email,
                password: settings.newPassword || undefined,
            });

            if (settings.geminiApiKey) {
                await updateClientKey(clientId, settings.geminiApiKey);
                setSettings((prev) => ({ ...prev, geminiApiKey: '' }));
            }

            await updateClientSettings(clientId, {
                currency: settings.currency,
                language: settings.language,
            });

            setSaved(true);
            showToast('Settings updated', 'success');
            refreshClients();
            setTimeout(() => setSaved(false), 2000);
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to save settings', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const handleExport = async () => {
        setIsExporting(true);
        try {
            const snapshot = await exportData();
            const datePart = new Date().toISOString().slice(0, 10);
            const fileName = `asset-management-client-${clientId}-${datePart}.json`;
            const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' });

            if ('showSaveFilePicker' in window) {
                try {
                    const handle = await (window as any).showSaveFilePicker({
                        suggestedName: fileName,
                        types: [{ description: 'JSON backup', accept: { 'application/json': ['.json'] } }],
                    });
                    const writable = await handle.createWritable();
                    await writable.write(blob);
                    await writable.close();
                    showToast('Export saved', 'success');
                    return;
                } catch (error: any) {
                    if (error?.name === 'AbortError') return;
                    throw error;
                }
            }

            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = fileName;
            link.click();
            URL.revokeObjectURL(url);
            showToast('Export downloaded', 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to export data', 'error');
        } finally {
            setIsExporting(false);
        }
    };

    const handleImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;

        const confirmed = window.confirm('Importing this file will replace all data for the signed-in user. Continue?');
        if (!confirmed) return;

        setIsImporting(true);
        try {
            const text = await file.text();
            let payload: unknown;
            try {
                payload = JSON.parse(text);
            } catch {
                throw new Error('Invalid JSON file');
            }
            await importData(payload);
            showToast('Import completed', 'success');
            refreshClients();
            setHealth(null);
        } catch (error: any) {
            showToast(error.response?.data?.detail || error.message || 'Failed to import data', 'error');
        } finally {
            setIsImporting(false);
        }
    };

    const runHealthCheck = async () => {
        setIsCheckingHealth(true);
        try {
            const result = await checkDataHealth();
            setHealth(result);
            showToast(result.total_issues ? 'Data check completed with issues' : 'Data check passed', result.total_issues ? 'warning' : 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to check data health', 'error');
        } finally {
            setIsCheckingHealth(false);
        }
    };

    const runHealthRepair = async () => {
        setIsRepairingHealth(true);
        try {
            const result = await repairDataHealth();
            setHealth(result.health);
            const updated = result.actions.reduce((total, action) => total + action.updated, 0);
            showToast(`Repair completed (${updated} updates)`, 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to repair data', 'error');
        } finally {
            setIsRepairingHealth(false);
        }
    };

    const beginMfaSetup = async () => {
        setIsMfaBusy(true);
        try {
            const setup = await startMfaSetup({ current_password: mfaPassword });
            setMfaSetup(setup);
            setMfaRecoveryCodes([]);
            showToast('MFA setup started', 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to start MFA setup', 'error');
        } finally {
            setIsMfaBusy(false);
        }
    };

    const confirmMfaSetup = async () => {
        setIsMfaBusy(true);
        try {
            const result = await verifyMfaSetup({ code: mfaCode });
            setMfaRecoveryCodes(result.recovery_codes);
            setMfaSetup(null);
            setMfaCode('');
            setMfaPassword('');
            await refreshMfaStatus();
            showToast('MFA enabled', 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to verify MFA code', 'error');
        } finally {
            setIsMfaBusy(false);
        }
    };

    const turnOffMfa = async () => {
        setIsMfaBusy(true);
        try {
            await disableMfa({ current_password: mfaPassword, code: mfaCode });
            setMfaSetup(null);
            setMfaRecoveryCodes([]);
            setMfaCode('');
            setMfaPassword('');
            await refreshMfaStatus();
            showToast('MFA disabled', 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to disable MFA', 'error');
        } finally {
            setIsMfaBusy(false);
        }
    };

    const regenerateRecoveryCodes = async () => {
        setIsMfaBusy(true);
        try {
            const result = await regenerateMfaRecoveryCodes({ current_password: mfaPassword, code: mfaCode });
            setMfaRecoveryCodes(result.recovery_codes);
            setMfaCode('');
            setMfaPassword('');
            await refreshMfaStatus();
            showToast('Recovery codes regenerated', 'success');
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to regenerate recovery codes', 'error');
        } finally {
            setIsMfaBusy(false);
        }
    };

    const fieldClass = 'w-full bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors';
    const labelClass = 'block text-[10px] text-slate-500 uppercase tracking-widest mb-1';
    const sectionClass = 'border-b border-slate-800 px-2 py-4 last:border-b-0';
    const tabClass = (tab: SettingsTab) =>
        `flex items-center gap-2 border-b px-3 py-2 text-xs transition-colors ${activeTab === tab
            ? 'border-emerald-400 text-emerald-300'
            : 'border-transparent text-slate-500 hover:text-slate-200'
        }`;

    const leftPane = (
        <div className="h-full overflow-y-auto overflow-x-hidden pr-1 scrollbar-subtle">
            <div className="border border-slate-800 bg-slate-900/70 p-4">
                <div className="mb-4 flex items-center gap-2">
                    <User size={18} className="text-emerald-400" />
                    <h2 className="text-sm font-semibold">User Profile</h2>
                </div>
                <div className="space-y-4">
                    <div>
                        <label className={labelClass}>Full Name</label>
                        <input
                            type="text"
                            value={settings.name}
                            onChange={(e) => setSettings({ ...settings, name: e.target.value })}
                            className={fieldClass}
                        />
                    </div>
                    <div>
                        <label className={labelClass}>Email Address</label>
                        <input
                            type="email"
                            value={settings.email}
                            onChange={(e) => setSettings({ ...settings, email: e.target.value })}
                            className={fieldClass}
                        />
                    </div>
                    <div>
                        <label className={labelClass}>Update Password</label>
                        <div className="relative">
                            <input
                                type={showPassword ? 'text' : 'password'}
                                value={settings.newPassword}
                                onChange={(e) => setSettings({ ...settings, newPassword: e.target.value })}
                                className={`${fieldClass} pr-10`}
                                placeholder="Leave blank to keep current"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPassword(!showPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                                aria-label="Toggle password visibility"
                                title="Toggle password visibility"
                            >
                                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <button
                onClick={handleSave}
                disabled={isSaving}
                className={`mt-3 flex w-full items-center justify-center gap-3 rounded-md py-3 text-sm font-bold shadow-lg transition-all ${saved
                    ? 'bg-emerald-500 text-white shadow-emerald-500/20 scale-95'
                    : 'bg-emerald-600 text-white hover:bg-emerald-500 hover:shadow-emerald-500/30'
                } disabled:opacity-50 active:scale-95`}
            >
                <Save size={18} />
                {isSaving ? 'Synchronizing...' : saved ? 'Successfully Saved' : 'Apply All Changes'}
            </button>
        </div>
    );

    const mfaTab = (
        <div className={sectionClass}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <ShieldCheck size={18} className="text-emerald-400" />
                    <h2 className="text-sm font-semibold">Multi-Factor Authentication</h2>
                </div>
                <span className={`border px-2 py-0.5 text-[10px] ${mfaStatus?.enabled ? 'border-emerald-500/40 text-emerald-300' : 'border-slate-700 text-slate-400'}`}>
                    {mfaStatus?.enabled ? 'Enabled' : 'Disabled'}
                </span>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                    <label className={labelClass}>Current Password</label>
                    <input
                        type="password"
                        value={mfaPassword}
                        onChange={(e) => setMfaPassword(e.target.value)}
                        className={fieldClass}
                        placeholder="Required for setup or changes"
                    />
                </div>
                <div>
                    <label className={labelClass}>Authenticator Code</label>
                    <input
                        type="text"
                        value={mfaCode}
                        onChange={(e) => setMfaCode(e.target.value)}
                        className={`${fieldClass} font-mono`}
                        placeholder="123456"
                    />
                </div>
            </div>

            {mfaSetup && (
                <div className="mt-3 border border-emerald-500/30 bg-emerald-950/20 p-3">
                    <div className="mb-2 text-[10px] uppercase tracking-widest text-emerald-300">Setup URI</div>
                    <textarea
                        readOnly
                        value={mfaSetup.otpauth_uri}
                        className="h-20 w-full resize-none border border-slate-800 bg-slate-950 p-2 font-mono text-[10px] text-slate-300"
                    />
                    <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]">
                        <input readOnly value={mfaSetup.manual_entry_key} className={`${fieldClass} font-mono`} />
                        <button
                            type="button"
                            onClick={confirmMfaSetup}
                            disabled={isMfaBusy || !mfaCode}
                            className="flex items-center justify-center gap-2 border border-emerald-500/40 px-3 py-2 text-xs text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"
                        >
                            <CheckCircle2 size={14} />
                            Verify
                        </button>
                    </div>
                </div>
            )}

            {mfaRecoveryCodes.length > 0 && (
                <div className="mt-3 border border-amber-500/30 bg-amber-950/10 p-3">
                    <div className="mb-2 text-[10px] uppercase tracking-widest text-amber-300">Recovery Codes</div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {mfaRecoveryCodes.map((code) => (
                            <code key={code} className="border border-slate-800 bg-slate-950 px-2 py-1 text-center text-xs text-slate-200">
                                {code}
                            </code>
                        ))}
                    </div>
                </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
                {!mfaStatus?.enabled && !mfaSetup && (
                    <button
                        type="button"
                        onClick={beginMfaSetup}
                        disabled={isMfaBusy || !mfaPassword}
                        className="flex items-center gap-2 border border-emerald-500/40 bg-slate-800/60 px-3 py-2 text-xs text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"
                    >
                        <ShieldCheck size={14} />
                        Start Setup
                    </button>
                )}
                {mfaStatus?.enabled && (
                    <>
                        <button
                            type="button"
                            onClick={regenerateRecoveryCodes}
                            disabled={isMfaBusy || (!mfaPassword && !mfaCode)}
                            className="flex items-center gap-2 border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs hover:border-amber-500 hover:text-amber-300 disabled:opacity-50"
                        >
                            <RefreshCw size={14} />
                            Recovery Codes
                        </button>
                        <button
                            type="button"
                            onClick={turnOffMfa}
                            disabled={isMfaBusy || (!mfaPassword && !mfaCode)}
                            className="flex items-center gap-2 border border-red-500/40 bg-slate-800/60 px-3 py-2 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                        >
                            <AlertTriangle size={14} />
                            Disable
                        </button>
                    </>
                )}
            </div>
            <div className="mt-2 text-[10px] text-slate-500">
                {mfaStatus?.enabled ? `${mfaStatus.recovery_codes_remaining} recovery codes remaining` : 'Authenticator app setup is available for this account.'}
            </div>
        </div>
    );

    const securityTab = (
        <>
            {mfaTab}
            <div className={sectionClass}>
                <div className="mb-3 flex items-center gap-2">
                    <Key size={18} className="text-amber-400" />
                    <h2 className="text-sm font-semibold">Gemini Security</h2>
                </div>
                <div className="relative">
                    <input
                        type={showApiKey ? 'text' : 'password'}
                        value={settings.geminiApiKey}
                        onChange={(e) => setSettings({ ...settings, geminiApiKey: e.target.value })}
                        placeholder="Paste new Gemini API key..."
                        className={`${fieldClass} pr-10 font-mono`}
                    />
                    <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                        aria-label="Toggle API key visibility"
                        title="Toggle API key visibility"
                    >
                        {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                </div>
                <div className="mt-3 flex items-center gap-2 text-[10px]">
                    <div className={`h-1.5 w-1.5 rounded-full ${currentClient?.has_key ? 'bg-emerald-500' : 'bg-slate-700'}`} />
                    <span className="text-slate-500">{currentClient?.has_key ? 'Remote key active' : 'No key configured'}</span>
                </div>
            </div>
        </>
    );

    const preferencesTab = (
        <div className={sectionClass}>
            <div className="mb-3 flex items-center gap-2">
                <PlusCircle size={18} className="text-cyan-400" />
                <h2 className="text-sm font-semibold">General Preferences</h2>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                    <label className={labelClass}>Currency</label>
                    <select
                        value={settings.currency}
                        onChange={(e) => setSettings({ ...settings, currency: e.target.value })}
                        className={fieldClass}
                    >
                        <option value="JPY">JPY</option>
                        <option value="USD">USD</option>
                        <option value="EUR">EUR</option>
                    </select>
                </div>
                <div>
                    <label className={labelClass}>Language</label>
                    <select
                        value={settings.language}
                        onChange={(e) => setSettings({ ...settings, language: e.target.value })}
                        className={fieldClass}
                    >
                        <option value="ja">Japanese</option>
                        <option value="en">English</option>
                    </select>
                </div>
            </div>
        </div>
    );

    const transferTab = (
        <div className={sectionClass}>
            <div className="mb-3 flex items-center gap-2">
                <Database size={18} className="text-purple-400" />
                <h2 className="text-sm font-semibold">Data Transfer</h2>
            </div>
            <input
                ref={importInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={handleImportFile}
            />
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <button
                    type="button"
                    onClick={handleExport}
                    disabled={isExporting || isImporting}
                    className="flex items-center justify-center gap-2 border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs font-medium transition-colors hover:border-purple-500 hover:text-purple-300 disabled:opacity-50"
                >
                    <Download size={14} />
                    {isExporting ? 'Exporting...' : 'Export JSON'}
                </button>
                <button
                    type="button"
                    onClick={() => importInputRef.current?.click()}
                    disabled={isExporting || isImporting}
                    className="flex items-center justify-center gap-2 border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs font-medium transition-colors hover:border-amber-500 hover:text-amber-300 disabled:opacity-50"
                >
                    <Upload size={14} />
                    {isImporting ? 'Importing...' : 'Import JSON'}
                </button>
            </div>
        </div>
    );

    const healthTab = (
        <div className={sectionClass}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <Activity size={18} className="text-emerald-400" />
                    <h2 className="text-sm font-semibold">Data Health</h2>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={runHealthCheck}
                        disabled={isCheckingHealth || isRepairingHealth}
                        className="flex items-center gap-2 border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs hover:border-emerald-500 hover:text-emerald-300 disabled:opacity-50"
                    >
                        <RefreshCw size={14} className={isCheckingHealth ? 'animate-spin' : ''} />
                        Check
                    </button>
                    <button
                        type="button"
                        onClick={runHealthRepair}
                        disabled={isCheckingHealth || isRepairingHealth}
                        className="flex items-center gap-2 border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs hover:border-amber-500 hover:text-amber-300 disabled:opacity-50"
                    >
                        <Wrench size={14} className={isRepairingHealth ? 'animate-pulse' : ''} />
                        Repair
                    </button>
                </div>
            </div>

            {!health ? (
                <div className="border border-slate-800 bg-slate-950/50 px-3 py-8 text-center text-xs text-slate-500">
                    No check results yet.
                </div>
            ) : (
                <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        <div className="border border-slate-800 bg-slate-950/50 px-3 py-2">
                            <div className="text-[10px] uppercase tracking-widest text-slate-500">Status</div>
                            <div className={health.total_issues ? 'mt-1 text-sm font-semibold text-amber-300' : 'mt-1 text-sm font-semibold text-emerald-300'}>
                                {health.total_issues ? 'Issues Found' : 'OK'}
                            </div>
                        </div>
                        <div className="border border-slate-800 bg-slate-950/50 px-3 py-2">
                            <div className="text-[10px] uppercase tracking-widest text-slate-500">Issues</div>
                            <div className="mt-1 text-sm font-semibold text-slate-100">{health.total_issues}</div>
                        </div>
                        <div className="border border-slate-800 bg-slate-950/50 px-3 py-2">
                            <div className="text-[10px] uppercase tracking-widest text-slate-500">Repairable</div>
                            <div className="mt-1 text-sm font-semibold text-slate-100">{health.repairable_groups}</div>
                        </div>
                    </div>

                    {health.issues.map((issue) => (
                        <div key={issue.code} className="border border-slate-800 bg-slate-950/40">
                            <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-3 py-2">
                                <div className="flex min-w-0 items-center gap-2">
                                    {issue.count ? (
                                        <AlertTriangle size={15} className={issue.severity === 'error' ? 'text-red-400' : 'text-amber-400'} />
                                    ) : (
                                        <CheckCircle2 size={15} className="text-emerald-400" />
                                    )}
                                    <div className="min-w-0">
                                        <div className="truncate text-xs font-semibold text-slate-100">{issue.title}</div>
                                        <div className="truncate text-[10px] text-slate-500">{issue.detail}</div>
                                    </div>
                                </div>
                                <span className={`shrink-0 border px-2 py-0.5 text-[10px] ${issue.count ? 'border-amber-500/40 text-amber-300' : 'border-emerald-500/40 text-emerald-300'}`}>
                                    {issue.count}
                                </span>
                            </div>
                            {issue.items.length > 0 && (
                                <div className="max-h-56 overflow-y-auto px-3 py-2 scrollbar-subtle">
                                    {issue.items.slice(0, 8).map((item, index) => (
                                        <pre key={`${issue.code}-${index}`} className="mb-2 overflow-x-auto border border-slate-800 bg-slate-900/70 p-2 text-[10px] leading-relaxed text-slate-400">
                                            {JSON.stringify(item, null, 2)}
                                        </pre>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );

    const rightPane = (
        <div className="h-full min-h-0 overflow-hidden border border-slate-800 bg-slate-900/70">
            <div className="flex flex-wrap border-b border-slate-800 px-2">
                <button type="button" onClick={() => setActiveTab('security')} className={tabClass('security')}>
                    <ShieldCheck size={14} />
                    Security
                </button>
                <button type="button" onClick={() => setActiveTab('preferences')} className={tabClass('preferences')}>
                    <PlusCircle size={14} />
                    Preferences
                </button>
                <button type="button" onClick={() => setActiveTab('transfer')} className={tabClass('transfer')}>
                    <Database size={14} />
                    Data Transfer
                </button>
                <button type="button" onClick={() => setActiveTab('health')} className={tabClass('health')}>
                    <Activity size={14} />
                    Data Health
                </button>
            </div>
            <div className="h-[calc(100%-41px)] overflow-y-auto overflow-x-hidden p-3 pr-2 scrollbar-subtle">
                {activeTab === 'security' && securityTab}
                {activeTab === 'preferences' && preferencesTab}
                {activeTab === 'transfer' && transferTab}
                {activeTab === 'health' && healthTab}
            </div>
        </div>
    );

    return (
        <div className="h-full min-h-0 overflow-hidden p-2">
            <SplitView left={leftPane} right={rightPane} />
        </div>
    );
}
