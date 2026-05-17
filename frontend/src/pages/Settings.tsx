import { type ChangeEvent, useEffect, useRef, useState } from 'react';
import {
    Database,
    Download,
    Eye,
    EyeOff,
    Key,
    Lock,
    PlusCircle,
    Save,
    Settings,
    ShieldCheck,
    Upload,
    User,
} from 'lucide-react';
import SplitView from '../components/SplitView';
import { useClient } from '../context/ClientContext';
import { useAuth } from '../context/AuthContext';
import { exportData, importData, updateClientKey, updateClientSettings, updateProfile } from '../api';
import { useToast } from '../components/Toast';

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
    const [showApiKey, setShowApiKey] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const [saved, setSaved] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [isExporting, setIsExporting] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
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
            showToast('Profile and settings updated successfully', 'success');
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
            const blob = new Blob([JSON.stringify(snapshot, null, 2)], {
                type: 'application/json',
            });

            if ('showSaveFilePicker' in window) {
                try {
                    const handle = await (window as any).showSaveFilePicker({
                        suggestedName: fileName,
                        types: [
                            {
                                description: 'JSON backup',
                                accept: { 'application/json': ['.json'] },
                            },
                        ],
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

        const confirmed = window.confirm(
            'Importing this file will replace all data for the signed-in user. Continue?'
        );
        if (!confirmed) return;

        setIsImporting(true);
        try {
            const text = await file.text();
            const payload = JSON.parse(text);
            await importData(payload);
            showToast('Import completed', 'success');
            refreshClients();
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to import data', 'error');
        } finally {
            setIsImporting(false);
        }
    };

    const fieldClass = 'w-full bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors';
    const labelClass = 'block text-[10px] text-slate-500 uppercase tracking-widest mb-1';
    const rowClass = 'border-b border-slate-800 px-2 py-4 last:border-b-0';

    const leftPane = (
        <div className="h-full overflow-y-auto overflow-x-hidden pr-1 space-y-3 scrollbar-subtle">
            <div className="border border-slate-800 bg-slate-900/70 p-4">
                <div className="flex items-center gap-2 mb-4">
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
                            placeholder="Enter your name"
                        />
                    </div>
                    <div>
                        <label className={labelClass}>Email Address</label>
                        <input
                            type="email"
                            value={settings.email}
                            onChange={(e) => setSettings({ ...settings, email: e.target.value })}
                            className={fieldClass}
                            placeholder="Enter your email"
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

            <div className="border border-slate-800 bg-slate-900/70 p-4">
                <div className="flex items-center gap-2 mb-3">
                    <ShieldCheck size={18} className="text-cyan-400" />
                    <h2 className="text-sm font-semibold">Signed-In Client</h2>
                </div>
                <div className="flex items-center justify-between gap-3 border border-slate-800 bg-slate-950/60 px-3 py-3">
                    <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-100">{currentClient?.name || user?.name || 'Current user'}</p>
                        <p className="mt-1 text-[10px] font-mono text-slate-500">ID: {clientId}</p>
                    </div>
                    <span className={`shrink-0 rounded px-2 py-0.5 text-[10px] ${currentClient?.has_key ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}`}>
                        {currentClient?.has_key ? 'Key Set' : 'Key Required'}
                    </span>
                </div>
                <p className="mt-3 text-[10px] leading-relaxed text-slate-500">
                    Client switching is disabled. To access another user, sign out and sign in with that account.
                </p>
            </div>
        </div>
    );

    const rightPane = (
        <div className="space-y-3 h-full min-h-0 flex flex-col overflow-hidden">
            <div className="border border-slate-800 bg-slate-900/70 p-3 flex-shrink-0">
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Settings className="text-emerald-400" size={18} />
                        <div>
                            <h1 className="text-sm font-semibold">Control Center</h1>
                            <p className="text-[10px] text-slate-500">Security, preferences, and data transfer</p>
                        </div>
                    </div>
                    <Lock size={15} className="text-slate-500" />
                </div>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden border border-slate-800 bg-slate-900/70 p-3 pr-2 scrollbar-subtle">
                <div className={rowClass}>
                    <div className="mb-3 flex items-center gap-2">
                        <Key size={18} className="text-amber-400" />
                        <h2 className="text-sm font-semibold">Gemini Security</h2>
                    </div>
                    <p className="mb-4 text-[10px] leading-relaxed text-slate-500">
                        Configure the Google Gemini API key for the signed-in user. Keys are encrypted before storage.
                    </p>
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
                        <span className="text-slate-500">
                            {currentClient?.has_key ? 'Remote key active' : 'No key configured'}
                        </span>
                    </div>
                </div>

                <div className={rowClass}>
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

                <div className={rowClass}>
                    <div className="mb-3 flex items-center gap-2">
                        <Database size={18} className="text-purple-400" />
                        <h2 className="text-sm font-semibold">Data Transfer</h2>
                    </div>
                    <p className="mb-4 text-[10px] leading-relaxed text-slate-500">
                        Export or restore the signed-in user's accounts, transactions, goals, budgets, products, and capsules.
                    </p>
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
            </div>

            <button
                onClick={handleSave}
                disabled={isSaving}
                className={`flex w-full flex-shrink-0 items-center justify-center gap-3 rounded-lg py-3 text-sm font-bold shadow-lg transition-all ${saved
                    ? 'bg-emerald-500 text-white shadow-emerald-500/20 scale-95'
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white hover:shadow-emerald-500/30'
                    } disabled:opacity-50 active:scale-95`}
            >
                <Save size={18} />
                {isSaving ? 'Synchronizing...' : saved ? 'Successfully Saved' : 'Apply All Changes'}
            </button>
        </div>
    );

    return (
        <div className="h-full min-h-0 overflow-hidden p-2">
            <SplitView left={leftPane} right={rightPane} />
        </div>
    );
}
