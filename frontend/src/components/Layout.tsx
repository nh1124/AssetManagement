import type { ReactNode } from 'react';
import { useAuth } from '../context/AuthContext';
import { BarChart3, Target, Package, Settings, Plus, LogOut, User as UserIcon, List } from 'lucide-react';

interface LayoutProps {
    children: ReactNode;
    currentPage: string;
    onNavigate: (page: string) => void;
    onOpenQuickInput: () => void;
}

const navItems = [
    { id: 'journal', label: 'Journal', icon: List },
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
    { id: 'strategy', label: 'Strategy', icon: Target },
    { id: 'registry', label: 'Registry', icon: Package },
    { id: 'settings', label: 'Settings', icon: Settings },
];

export default function Layout({ children, currentPage, onNavigate, onOpenQuickInput }: LayoutProps) {
    const { user, logout } = useAuth();

    return (
        <div className="min-h-screen bg-slate-900 text-slate-50 flex flex-col">
            {/* Top Navigation */}
            <nav className="bg-slate-900 border-b border-slate-800 flex-shrink-0">
                <div className="px-3">
                    <div className="flex items-center justify-between h-10">
                        <div className="flex items-center space-x-2">
                            <div className="w-6 h-6 bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center">
                                <span className="text-white font-bold text-[10px]">FI</span>
                            </div>
                            <span className="font-medium text-sm">Finance IDE</span>
                            <span className="text-[10px] text-slate-600 ml-1">v3.0</span>
                        </div>

                        <div className="flex flex-1 justify-center">
                            {navItems.map((item) => {
                                const Icon = item.icon;
                                const isActive = currentPage === item.id;
                                return (
                                    <button
                                        key={item.id}
                                        onClick={() => onNavigate(item.id)}
                                        className={`flex items-center space-x-1.5 px-4 py-1.5 text-xs transition-colors border-b-2 ${isActive
                                            ? 'border-emerald-400 text-emerald-400 bg-slate-800/50'
                                            : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30'
                                            }`}
                                    >
                                        <Icon size={14} />
                                        <span>{item.label}</span>
                                    </button>
                                );
                            })}
                        </div>

                        <div className="flex items-center space-x-2">
                            <div className="flex items-center text-[10px] text-slate-500 bg-slate-800/50 px-2 py-0.5 rounded border border-slate-700">
                                <UserIcon size={10} className="mr-1" />
                                <span>{user?.name || 'Guest'}</span>
                            </div>
                            <button
                                onClick={logout}
                                className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-950/20 transition-all rounded"
                                title="Sign Out"
                            >
                                <LogOut size={14} />
                            </button>
                        </div>
                    </div>
                </div>
            </nav>


            {/* Main Content */}
            <main className="flex-1 overflow-hidden relative">
                {children}

                {/* Floating Action Button for Quick Input */}
                <button
                    onClick={onOpenQuickInput}
                    className="fixed bottom-6 right-6 w-14 h-14 bg-gradient-to-br from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 rounded-full shadow-lg shadow-emerald-500/25 flex items-center justify-center transition-all hover:scale-105 z-40"
                    title="Quick Record"
                >
                    <Plus size={24} className="text-white" />
                </button>
            </main>
        </div>
    );
}
