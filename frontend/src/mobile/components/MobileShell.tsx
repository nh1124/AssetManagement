import type { ReactNode } from 'react';
import { LogOut, User as UserIcon } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useClient } from '../../context/ClientContext';
import MobileBottomNav, { type MobilePage } from './MobileBottomNav';

interface MobileShellProps {
    children: ReactNode;
    currentPage: MobilePage;
    onNavigate: (page: MobilePage) => void;
}

export default function MobileShell({ children, currentPage, onNavigate }: MobileShellProps) {
    const { user, logout } = useAuth();
    const { currentClient } = useClient();

    return (
        <div className="h-dvh min-h-0 bg-slate-950 text-slate-50 flex flex-col overflow-hidden">
            <header className="flex h-12 flex-shrink-0 items-center justify-between border-b border-slate-800 px-3">
                <div className="min-w-0">
                    <div className="flex items-center gap-2">
                        <div className="flex h-7 w-7 items-center justify-center bg-gradient-to-br from-emerald-400 to-cyan-500">
                            <span className="text-[10px] font-bold text-white">FI</span>
                        </div>
                        <div className="min-w-0">
                            <p className="truncate text-sm font-medium">Finance IDE</p>
                            <p className="truncate text-[10px] text-slate-500">{currentClient?.name ?? 'Default client'}</p>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <div className="flex max-w-28 items-center gap-1 truncate border border-slate-800 bg-slate-900 px-2 py-1 text-[10px] text-slate-400">
                        <UserIcon size={11} />
                        <span className="truncate">{user?.name || 'Guest'}</span>
                    </div>
                    <button
                        type="button"
                        onClick={logout}
                        className="p-2 text-slate-500 active:text-rose-300"
                        aria-label="Sign out"
                    >
                        <LogOut size={17} />
                    </button>
                </div>
            </header>

            <main className="scrollbar-none flex-1 min-h-0 overflow-y-auto overflow-x-hidden pb-[calc(4rem+env(safe-area-inset-bottom))]">
                {children}
            </main>
            <MobileBottomNav currentPage={currentPage} onNavigate={onNavigate} />
        </div>
    );
}
