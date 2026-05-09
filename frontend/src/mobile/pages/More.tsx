import { Database, Flag, Package, Settings, ShieldCheck, Target, WalletCards } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useClient } from '../../context/ClientContext';

export default function MobileMorePage() {
    const { user } = useAuth();
    const { currentClient, clients } = useClient();

    const modules = [
        { label: 'Portfolio', status: 'Desktop deep view', icon: WalletCards },
        { label: 'Goal', status: 'Compact summary lives in Plan', icon: Flag },
        { label: 'Strategy', status: 'Desktop planning view', icon: Target },
        { label: 'Registry', status: 'Desktop catalog view', icon: Package },
        { label: 'Settings', status: 'Desktop admin view', icon: Settings },
    ];

    return (
        <div className="space-y-4 p-3">
            <section>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">More</p>
                <h1 className="text-xl font-semibold text-slate-50">Workspace</h1>
            </section>

            <section className="grid grid-cols-2 gap-2">
                <InfoTile icon={ShieldCheck} label="Signed in" value={user?.name || 'Guest'} />
                <InfoTile icon={Database} label="Client" value={currentClient?.name || `Client ${clients.length ? '' : '1'}`} />
            </section>

            <section className="space-y-2">
                <h2 className="text-sm font-medium text-slate-100">Modules</h2>
                <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                    {modules.map((item) => {
                        const Icon = item.icon;
                        return (
                            <article key={item.label} className="flex items-center gap-3 px-3 py-3">
                                <div className="flex h-9 w-9 items-center justify-center border border-slate-800 bg-slate-950 text-slate-500">
                                    <Icon size={17} />
                                </div>
                                <div className="min-w-0">
                                    <p className="truncate text-sm font-medium text-slate-100">{item.label}</p>
                                    <p className="truncate text-[10px] text-slate-500">{item.status}</p>
                                </div>
                            </article>
                        );
                    })}
                </div>
            </section>

            <section className="border border-slate-800 bg-slate-900/60 p-3">
                <p className="text-sm font-medium text-slate-100">Mobile boundary</p>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                    Mobile screens are separate from desktop screens. Shared code is limited to API clients, types, auth/client context, format utilities, and domain logic.
                </p>
            </section>
        </div>
    );
}

function InfoTile({
    icon: Icon,
    label,
    value,
}: {
    icon: typeof ShieldCheck;
    label: string;
    value: string;
}) {
    return (
        <div className="min-w-0 border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-center gap-2 text-slate-500">
                <Icon size={15} />
                <p className="text-[10px] uppercase tracking-wide">{label}</p>
            </div>
            <p className="mt-2 truncate text-sm text-slate-100">{value}</p>
        </div>
    );
}
