import type { ReactNode } from 'react';
import { Home, FlaskConical, Target } from 'lucide-react';

interface LayoutProps {
    children: ReactNode;
    currentPage: string;
    onNavigate: (page: string) => void;
}

const navItems = [
    { id: 'home', label: 'Home', icon: Home },
    { id: 'lab', label: 'The Lab', icon: FlaskConical },
    { id: 'strategy', label: 'Strategy', icon: Target },
];

export default function Layout({ children, currentPage, onNavigate }: LayoutProps) {
    return (
        <div className="min-h-screen bg-slate-900 text-slate-50">
            {/* Top Navigation */}
            <nav className="bg-slate-800/80 backdrop-blur-md border-b border-slate-700 sticky top-0 z-50">
                <div className="max-w-7xl mx-auto px-4">
                    <div className="flex items-center justify-between h-14">
                        <div className="flex items-center space-x-2">
                            <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-cyan-500 rounded-lg flex items-center justify-center">
                                <span className="text-white font-bold text-sm">AM</span>
                            </div>
                            <span className="font-semibold text-lg">Asset Manager</span>
                        </div>
                        <div className="flex space-x-1">
                            {navItems.map((item) => {
                                const Icon = item.icon;
                                const isActive = currentPage === item.id;
                                return (
                                    <button
                                        key={item.id}
                                        onClick={() => onNavigate(item.id)}
                                        className={`flex items-center space-x-2 px-4 py-2 rounded-lg transition-all duration-200 ${isActive
                                            ? 'bg-slate-700 text-emerald-400'
                                            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                                            }`}
                                    >
                                        <Icon size={18} />
                                        <span className="text-sm font-medium">{item.label}</span>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                </div>
            </nav>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto px-4 py-6">
                {children}
            </main>
        </div>
    );
}
