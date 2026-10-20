import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Bell, BookOpen, ChevronLeft, Flag, Home, Menu, PieChart, Plus } from 'lucide-react';
import type { Transaction } from '../../types';
import { useNotifications } from '../../studio/notificationContext';
import RecordSheet from '../pages/RecordSheet';
import { RecordingContext } from './recording';
import { focusRing } from './ui';

/** A screen: a sticky translucent header (title, back, actions) over its content. */
export function Screen({ title, back, actions, top = false, children }: {
    /** back: a path, or -1 for wherever the user came from. */
    title: string; back?: string | -1; actions?: ReactNode; top?: boolean; children: ReactNode;
}) {
    const navigate = useNavigate();
    const { items } = useNotifications();
    const iconButton = `relative flex h-11 w-11 items-center justify-center rounded-full text-[var(--studio-text)] active:bg-[var(--studio-accent-soft)] ${focusRing}`;
    return <>
        <header className="sticky top-0 z-30 border-b border-[var(--studio-border)]/70 bg-[var(--mobile-bar)] pt-[env(safe-area-inset-top)] backdrop-blur-md">
            <div className="mx-auto flex h-14 max-w-lg items-center gap-1 px-2">
                {back !== undefined ? <button type="button" onClick={() => { if (back === -1) navigate(-1); else navigate(back); }} aria-label="戻る" className={iconButton}><ChevronLeft size={22} aria-hidden /></button> : <span className="w-2" />}
                <h1 className="min-w-0 flex-1 truncate text-lg font-bold tracking-tight">{title}</h1>
                {actions}
                {top && <>
                    <button type="button" onClick={() => navigate('/notifications')} aria-label={`通知${items.length ? `（${items.length}件）` : ''}`} className={iconButton}>
                        <Bell size={20} aria-hidden />
                        {items.length > 0 && <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--studio-danger)] px-1 text-[10px] font-bold text-white">{items.length}</span>}
                    </button>
                    <button type="button" onClick={() => navigate('/more')} aria-label="メニュー" className={iconButton}><Menu size={20} aria-hidden /></button>
                </>}
            </div>
        </header>
        <div className="mx-auto max-w-lg space-y-4 px-4 pb-6 pt-4">{children}</div>
    </>;
}

const TABS = [
    { to: '/', label: 'ホーム', icon: Home, end: true },
    { to: '/ledger', label: '家計簿', icon: BookOpen, end: false },
    { to: '/plan', label: '計画', icon: PieChart, end: false },
    { to: '/goals', label: 'ゴール', icon: Flag, end: false },
];

function TabBar({ onRecord }: { onRecord: () => void }) {
    const tab = ({ to, label, icon: Icon, end }: typeof TABS[number]) => <NavLink key={to} to={to} end={end}
        className={({ isActive }) => `flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${focusRing} ${isActive ? 'text-[var(--studio-accent)]' : 'text-[var(--studio-text-muted)]'}`}>
        {({ isActive }) => <><Icon size={22} strokeWidth={isActive ? 2.4 : 1.8} aria-hidden /><span>{label}</span></>}
    </NavLink>;
    return <nav aria-label="メイン" className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--studio-border)]/70 bg-[var(--mobile-bar)] pb-[env(safe-area-inset-bottom)] backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-lg items-stretch px-2">
            {TABS.slice(0, 2).map(tab)}
            <div className="flex w-20 items-start justify-center">
                <button type="button" onClick={onRecord} aria-label="取引を記録"
                    className={`-mt-5 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--studio-accent)] text-white shadow-[var(--mobile-shadow-raised)] active:scale-95 ${focusRing}`}>
                    <Plus size={28} strokeWidth={2.4} aria-hidden />
                </button>
            </div>
            {TABS.slice(2).map(tab)}
        </div>
    </nav>;
}

/** The mobile frame: the routed screen, the tab bar, and the record sheet any screen can open. */
export default function Layout() {
    const [editing, setEditing] = useState<Transaction | null | undefined>(undefined);
    const [revision, setRevision] = useState(0);
    const changed = useCallback(() => setRevision((value) => value + 1), []);
    const recording = useMemo(() => ({ open: (transaction?: Transaction) => setEditing(transaction ?? null), revision, changed }), [revision, changed]);
    return <RecordingContext.Provider value={recording}>
        <div className="flex h-dvh flex-col">
            <main className="mobile-scroll min-h-0 flex-1 overflow-y-auto pb-[calc(5rem+env(safe-area-inset-bottom))]">
                {/* A save remounts the screen so everything on it loads again; screens keep their month in the URL. */}
                <div key={revision}><Outlet /></div>
            </main>
            <TabBar onRecord={() => setEditing(null)} />
            {editing !== undefined && <RecordSheet transaction={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); changed(); }} />}
        </div>
    </RecordingContext.Provider>;
}
