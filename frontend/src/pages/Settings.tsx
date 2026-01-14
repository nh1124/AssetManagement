import { useState } from 'react';
import { Save, User, Database, Bell } from 'lucide-react';

export default function SettingsPage() {
    const [settings, setSettings] = useState({
        currency: 'JPY',
        language: 'ja',
        notifications: true,
        darkMode: true,
    });

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
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Currency</label>
                            <select
                                value={settings.currency}
                                onChange={(e) => setSettings({ ...settings, currency: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                <option value="JPY">¥ JPY</option>
                                <option value="USD">$ USD</option>
                                <option value="EUR">€ EUR</option>
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
                <button className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 text-sm font-medium flex items-center justify-center gap-2 transition-colors">
                    <Save size={16} />
                    Save Settings
                </button>
            </div>
        </div>
    );
}
