import { useState, useEffect } from 'react';
import { Save, User, Database, Bell, Key, Eye, EyeOff } from 'lucide-react';

export default function SettingsPage() {
    const [settings, setSettings] = useState({
        currency: 'JPY',
        language: 'ja',
        notifications: true,
        geminiApiKey: '',
    });
    const [showApiKey, setShowApiKey] = useState(false);
    const [saved, setSaved] = useState(false);

    // Load saved API key from localStorage
    useEffect(() => {
        const savedKey = localStorage.getItem('gemini_api_key');
        if (savedKey) {
            setSettings(prev => ({ ...prev, geminiApiKey: savedKey }));
        }
    }, []);

    const handleSave = () => {
        // Save API key to localStorage
        if (settings.geminiApiKey) {
            localStorage.setItem('gemini_api_key', settings.geminiApiKey);
        }
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
    };

    return (
        <div className="h-full overflow-auto p-4">
            <h1 className="text-lg font-semibold mb-4">Settings</h1>

            <div className="max-w-2xl space-y-4">
                {/* Profile Section */}
                <div className="border border-slate-800 p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <User size={16} className="text-slate-400" />
                        <h2 className="text-sm font-medium">Profile</h2>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Default Currency</label>
                            <select
                                value={settings.currency}
                                onChange={(e) => setSettings({ ...settings, currency: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                <option value="JPY">¥ JPY</option>
                                <option value="USD">$ USD</option>
                                <option value="EUR">€ EUR</option>
                                <option value="GBP">£ GBP</option>
                                <option value="CNY">¥ CNY</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Language</label>
                            <select
                                value={settings.language}
                                onChange={(e) => setSettings({ ...settings, language: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                <option value="ja">日本語</option>
                                <option value="en">English</option>
                            </select>
                        </div>
                    </div>
                </div>

                {/* Gemini API Key */}
                <div className="border border-slate-800 p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <Key size={16} className="text-amber-400" />
                        <h2 className="text-sm font-medium">Gemini API Key</h2>
                    </div>
                    <p className="text-[10px] text-slate-500 mb-2">Used for AI-powered analysis and insights</p>
                    <div className="relative">
                        <input
                            type={showApiKey ? 'text' : 'password'}
                            value={settings.geminiApiKey}
                            onChange={(e) => setSettings({ ...settings, geminiApiKey: e.target.value })}
                            placeholder="Enter your Gemini API key..."
                            className="w-full bg-slate-800 border border-slate-700 px-3 py-2 pr-10 text-sm font-mono focus:outline-none focus:border-emerald-500"
                        />
                        <button
                            type="button"
                            onClick={() => setShowApiKey(!showApiKey)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                        >
                            {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                    </div>
                    <p className="text-[10px] text-slate-600 mt-1">
                        Get your API key from <a href="https://aistudio.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyan-500 hover:underline">Google AI Studio</a>
                    </p>
                </div>

                {/* Notifications */}
                <div className="border border-slate-800 p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <Bell size={16} className="text-slate-400" />
                        <h2 className="text-sm font-medium">Notifications</h2>
                    </div>
                    <label className="flex items-center gap-2 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={settings.notifications}
                            onChange={(e) => setSettings({ ...settings, notifications: e.target.checked })}
                            className="w-4 h-4 accent-emerald-500"
                        />
                        <span className="text-sm">Enable notifications</span>
                    </label>
                </div>

                {/* Database */}
                <div className="border border-slate-800 p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <Database size={16} className="text-slate-400" />
                        <h2 className="text-sm font-medium">Data</h2>
                    </div>
                    <div className="flex gap-2">
                        <button className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 transition-colors">
                            Export Data
                        </button>
                        <button className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 transition-colors">
                            Import Data
                        </button>
                    </div>
                </div>

                {/* Save Button */}
                <button
                    onClick={handleSave}
                    className={`w-full py-2.5 text-sm font-medium flex items-center justify-center gap-2 transition-colors ${saved
                            ? 'bg-emerald-700 text-white'
                            : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                        }`}
                >
                    <Save size={16} />
                    {saved ? 'Saved!' : 'Save Settings'}
                </button>
            </div>
        </div>
    );
}
