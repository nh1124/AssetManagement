import { ClipboardCheck, Grid2X2, List, Target, WalletCards } from 'lucide-react';

export type MobilePage = 'quick' | 'journal' | 'portfolio' | 'plan' | 'review' | 'more';

interface MobileBottomNavProps {
    currentPage: MobilePage;
    onNavigate: (page: MobilePage) => void;
}

const navItems = [
    { id: 'quick', label: 'Quick', icon: Grid2X2 },
    { id: 'journal', label: 'Journal', icon: List },
    { id: 'portfolio', label: 'Portfolio', icon: WalletCards },
    { id: 'plan', label: 'Plan', icon: Target },
    { id: 'review', label: 'Review', icon: ClipboardCheck },
] satisfies Array<{ id: MobilePage; label: string; icon: typeof Grid2X2 }>;

export default function MobileBottomNav({ currentPage, onNavigate }: MobileBottomNavProps) {
    return (
        <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-800 bg-slate-950/95 backdrop-blur supports-[padding:max(0px)]:pb-[env(safe-area-inset-bottom)]">
            <div className="grid h-16 grid-cols-5">
                {navItems.map((item) => {
                    const Icon = item.icon;
                    const isActive = currentPage === item.id;
                    return (
                        <button
                            key={item.id}
                            type="button"
                            onClick={() => onNavigate(item.id)}
                            className={`flex flex-col items-center justify-center gap-1 text-[10px] transition-colors ${isActive
                                ? 'text-emerald-300'
                                : 'text-slate-500 active:text-slate-200'
                                }`}
                            aria-label={item.label}
                        >
                            <Icon size={19} />
                            <span>{item.label}</span>
                        </button>
                    );
                })}
            </div>
        </nav>
    );
}
