import { useState } from 'react';
import { Save, User, Key, Eye, EyeOff, Users, Plus, Settings, PlusCircle } from 'lucide-react';
import { useClient } from '../context/ClientContext';
import { useAuth } from '../context/AuthContext';
import { updateClientKey, updateProfile } from '../api';
import { useToast } from '../components/Toast';

export default function SettingsPage() {
    const { user } = useAuth();
    const { clientId, setClientId, clients, refreshClients } = useClient();
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

    const handleSave = async () => {
        setIsSaving(true);
        try {
            // 1. Update Profile (auth/me)
            await updateProfile({
                name: settings.name,
                email: settings.email,
                password: settings.newPassword || undefined
            });

            // 2. Save API key to backend (encrypted)
            if (settings.geminiApiKey) {
                await updateClientKey(clientId, settings.geminiApiKey);
                setSettings(prev => ({ ...prev, geminiApiKey: '' }));
            }

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

    const currentClient = clients.find(c => c.id === clientId);

    return (
        <div className="h-full overflow-auto p-4 max-w-4xl mx-auto">
            <h1 className="text-lg font-semibold mb-6 flex items-center gap-2">
                <Settings className="text-emerald-400" size={20} />
                Control Center
            </h1>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-6">
                    {/* User Profile Section */}
                    <div className="border border-slate-800 p-5 bg-slate-900/30 rounded-lg">
                        <div className="flex items-center gap-2 mb-4">
                            <User size={18} className="text-emerald-400" />
                            <h2 className="text-sm font-semibold">User Profile</h2>
                        </div>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Full Name</label>
                                <input
                                    type="text"
                                    value={settings.name}
                                    onChange={(e) => setSettings({ ...settings, name: e.target.value })}
                                    className="w-full bg-slate-800/50 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                                    placeholder="Enter your name"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Email Address</label>
                                <input
                                    type="email"
                                    value={settings.email}
                                    onChange={(e) => setSettings({ ...settings, email: e.target.value })}
                                    className="w-full bg-slate-800/50 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                                    placeholder="Enter your email"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Update Password</label>
                                <div className="relative">
                                    <input
                                        type={showPassword ? 'text' : 'password'}
                                        value={settings.newPassword}
                                        onChange={(e) => setSettings({ ...settings, newPassword: e.target.value })}
                                        className="w-full bg-slate-800/50 border border-slate-700 px-3 py-2 pr-10 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                                        placeholder="Leave blank to keep current"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(!showPassword)}
                                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                                    >
                                        {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Client Selection (SaaS Context) */}
                    <div className="border border-slate-800 p-5 bg-slate-900/30 rounded-lg">
                        <div className="flex items-center gap-2 mb-4">
                            <Users size={18} className="text-cyan-400" />
                            <h2 className="text-sm font-semibold">Active Client Context</h2>
                        </div>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Switch Tenant</label>
                                <div className="flex gap-2">
                                    <select
                                        value={clientId}
                                        onChange={(e) => setClientId(parseInt(e.target.value))}
                                        className="flex-1 bg-slate-800/50 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 appearance-none transition-colors"
                                    >
                                        {clients.map(c => (
                                            <option key={c.id} value={c.id}>
                                                {c.name} {c.has_key ? ' (Key Set)' : ' (Key Missing)'}
                                            </option>
                                        ))}
                                    </select>
                                    <button
                                        className="px-3 bg-slate-800/50 border border-slate-700 hover:bg-slate-700 transition-colors"
                                        onClick={() => {/* TODO: Add new client */ }}
                                    >
                                        <Plus size={16} />
                                    </button>
                                </div>
                            </div>
                            <div className="flex items-center justify-between p-3 bg-slate-950/50 border border-slate-800 rounded">
                                <span className="text-[10px] text-slate-500 font-mono">ID: {currentClient?.id}</span>
                                <span className={`text-[10px] px-2 py-0.5 rounded ${currentClient?.has_key ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}`}>
                                    {currentClient?.has_key ? 'Authenticated' : 'Key Required'}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="space-y-6">
                    {/* Gemini API Key */}
                    <div className="border border-slate-800 p-5 bg-slate-900/30 rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                            <Key size={18} className="text-amber-400" />
                            <h2 className="text-sm font-semibold">Gemini Security</h2>
                        </div>
                        <p className="text-[10px] text-slate-500 mb-4 leading-relaxed">
                            Configure your Google Gemini API key for this specific tenant context.
                            Keys are encrypted using Fernet-AES.
                        </p>
                        <div className="relative">
                            <input
                                type={showApiKey ? 'text' : 'password'}
                                value={settings.geminiApiKey}
                                onChange={(e) => setSettings({ ...settings, geminiApiKey: e.target.value })}
                                placeholder="Paste new Gemini API key..."
                                className="w-full bg-slate-800/50 border border-slate-700 px-3 py-2 pr-10 text-sm font-mono focus:outline-none focus:border-emerald-500 transition-colors"
                            />
                            <button
                                type="button"
                                onClick={() => setShowApiKey(!showApiKey)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                            >
                                {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                            </button>
                        </div>
                        <div className="mt-4 flex items-center gap-2 text-[10px]">
                            <div className={`w-1.5 h-1.5 rounded-full ${currentClient?.has_key ? 'bg-emerald-500' : 'bg-slate-700'}`} />
                            <span className="text-slate-500">
                                {currentClient?.has_key ? 'Remote Key Active' : 'No Key Configured'}
                            </span>
                        </div>
                    </div>

                    {/* Preferences */}
                    <div className="border border-slate-800 p-5 bg-slate-900/30 rounded-lg">
                        <div className="flex items-center gap-2 mb-4">
                            <PlusCircle size={18} className="text-cyan-400" />
                            <h2 className="text-sm font-semibold">General Preferences</h2>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Currency</label>
                                <select
                                    value={settings.currency}
                                    onChange={(e) => setSettings({ ...settings, currency: e.target.value })}
                                    className="w-full bg-slate-800/50 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                                >
                                    <option value="JPY">¥ JPY</option>
                                    <option value="USD">$ USD</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Language</label>
                                <select
                                    value={settings.language}
                                    onChange={(e) => setSettings({ ...settings, language: e.target.value })}
                                    className="w-full bg-slate-800/50 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                                >
                                    <option value="ja">日本語</option>
                                    <option value="en">English</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    {/* Actions */}
                    <div className="pt-2">
                        <button
                            onClick={handleSave}
                            disabled={isSaving}
                            className={`w-full py-3 text-sm font-bold flex items-center justify-center gap-3 rounded-lg transition-all shadow-lg ${saved
                                ? 'bg-emerald-500 text-white shadow-emerald-500/20 scale-95'
                                : 'bg-emerald-600 hover:bg-emerald-500 text-white hover:shadow-emerald-500/30'
                                } disabled:opacity-50 active:scale-95`}
                        >
                            <Save size={18} />
                            {isSaving ? 'Synchronizing...' : saved ? 'Successfully Saved' : 'Apply All Changes'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
