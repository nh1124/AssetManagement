import type { ReactNode } from 'react';
import { Home, FlaskConical, Target, Wallet, Package } from 'lucide-react';

interface LayoutProps {
    children: ReactNode;
    currentPage: string;
    onNavigate: (page: string) => void;
}

const navItems = [
    { id: 'home', label: 'Home', icon: Home },
    { id: 'lab', label: 'The Lab', icon: FlaskConical },
    { id: 'budget', label: 'Budget', icon: Wallet },
    { id: 'products', label: 'Products', icon: Package },
    { id: 'strategy', label: 'Strategy', icon: Target },
];

export default function Layout({ children, currentPage, onNavigate }: LayoutProps) {
    return (
        <div className="min-h-screen bg-slate-900 text-slate-50 flex flex-col">
            {/* Top Navigation */}
            <nav className="bg-slate-900 border-b border-slate-800 flex-shrink-0">
                <div className="px-3">
                    <div className="flex items-center justify-between h-10">
                        <div className="flex items-center space-x-2">
                            <div className="w-6 h-6 bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center">
                                <span className="text-white font-bold text-[10px]">AM</span>
                            </div>
                            <span className="font-medium text-sm">Asset Manager</span>
                        </div>
                        <div className="flex">
                            {navItems.map((item) => {
                                const Icon = item.icon;
                                const isActive = currentPage === item.id;
                                return (
                                    <button
                                        key={item.id}
                                        onClick={() => onNavigate(item.id)}
                                        className={`flex items-center space-x-1.5 px-3 py-1.5 text-xs transition-colors border-b-2 ${isActive
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
                    </div>
                </div>
            </nav>

            {/* Main Content - Full Height */}
            <main className="flex-1 overflow-hidden">
                {children}
            </main>
        </div>
    );
}
