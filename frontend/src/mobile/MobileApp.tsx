import { useState } from 'react';
import { Flag, Package, Settings, Target, WalletCards } from 'lucide-react';
import MobileShell from './components/MobileShell';
import type { MobilePage } from './components/MobileBottomNav';
import MobileQuickPage from './pages/Quick';
import MobilePlaceholder from './pages/MobilePlaceholder';

export default function MobileApp() {
    const [currentPage, setCurrentPage] = useState<MobilePage>('quick');

    const renderPage = () => {
        switch (currentPage) {
            case 'quick':
                return <MobileQuickPage />;
            case 'journal':
                return (
                    <MobilePlaceholder title="Journal">
                        Mobile Journal will be built separately from the desktop transaction table. For now, use Quick for daily entry and desktop for deep edits.
                    </MobilePlaceholder>
                );
            case 'plan':
                return (
                    <MobilePlaceholder title="Plan">
                        Goal and Strategy workflows will get compact mobile views after the Quick and Approval flows settle.
                    </MobilePlaceholder>
                );
            case 'review':
                return (
                    <MobilePlaceholder title="Review">
                        Monthly and period review actions are available from the Quick approval inbox first. Full mobile review comes next.
                    </MobilePlaceholder>
                );
            case 'more':
                return <MobileMore />;
            default:
                return <MobileQuickPage />;
        }
    };

    return (
        <MobileShell currentPage={currentPage} onNavigate={setCurrentPage}>
            {renderPage()}
        </MobileShell>
    );
}

function MobileMore() {
    const items = [
        { label: 'Portfolio', icon: WalletCards },
        { label: 'Goal', icon: Flag },
        { label: 'Strategy', icon: Target },
        { label: 'Registry', icon: Package },
        { label: 'Settings', icon: Settings },
    ];

    return (
        <div className="p-4">
            <section className="space-y-2">
                <p className="text-[10px] uppercase tracking-wide text-slate-500">More</p>
                <h1 className="text-lg font-semibold text-slate-100">Mobile modules</h1>
                <p className="text-sm leading-6 text-slate-400">
                    These areas stay separate from the desktop screens and will be implemented as focused mobile workflows.
                </p>
            </section>
            <div className="mt-4 divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                {items.map((item) => {
                    const Icon = item.icon;
                    return (
                        <div key={item.label} className="flex items-center gap-3 px-3 py-3 text-slate-300">
                            <Icon size={18} className="text-slate-500" />
                            <span className="text-sm">{item.label}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
