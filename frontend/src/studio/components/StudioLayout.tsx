import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { ChevronRight, LogOut, PanelLeftClose, PanelLeftOpen, Settings as SettingsIcon } from 'lucide-react';
import { useClient } from '../../context/ClientContext';
import AppMark from './AppMark';
import NotificationBell from './NotificationBell';
import NotificationsProvider from './NotificationsProvider';
import { useLanguage } from '../i18n';
import { useAuth } from '../../context/AuthContext';
import { SETTINGS_PATH, STUDIO_GROUPS, STUDIO_HOME, STUDIO_SCREENS, type StudioScreen } from '../navigation';
import ConfirmProvider from './ConfirmProvider';

/** The screen whose path is the longest prefix of the current location.
 *
 * Longest wins so that "db/accounts" is not shadowed by a future "db", and a
 * tab route ("flows/accounts") still resolves to its screen.
 */
function useCurrentScreen() {
    const { pathname } = useLocation();
    const here = pathname.replace(/^\/+|\/+$/g, '');
    return STUDIO_SCREENS
        .filter((screen) => here === screen.path || here.startsWith(`${screen.path}/`))
        .sort((a, b) => b.path.length - a.path.length)[0];
}

const RAIL_OPEN_KEY = 'studio.rail.open';
const RAIL_COLLAPSED_KEY = 'studio.rail.collapsed';

/** Ids of the collapsible groups the user opened. Storage may be unavailable. */
function readOpenGroups(): string[] {
    try {
        const stored: unknown = JSON.parse(localStorage.getItem(RAIL_OPEN_KEY) ?? '[]');
        return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : [];
    } catch {
        return [];
    }
}

function readCollapsed(): boolean {
    try {
        return localStorage.getItem(RAIL_COLLAPSED_KEY) === '1';
    } catch {
        return false;
    }
}

const ICON_STROKE = 1.75;

const railLinkClass = ({ isActive }: { isActive: boolean }) =>
    `mx-2 flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
        isActive
            ? 'bg-[var(--studio-rail-active)] text-[var(--studio-rail-text-strong)]'
            : 'hover:bg-[var(--studio-rail-active)]/50'
    }`;

// Icon buttons share one size on the rail and in the header, so the row reads the same in both places.
const railIconClass = 'relative flex h-7 w-7 items-center justify-center rounded-md text-[var(--studio-rail-group)] transition-colors hover:bg-[var(--studio-rail-active)] hover:text-[var(--studio-rail-text-strong)]';
const headerIconClass = 'relative flex h-7 w-7 items-center justify-center rounded-md text-[var(--studio-text-muted)] transition-colors hover:bg-[var(--studio-accent-soft)] hover:text-[var(--studio-text)]';

function RailLink({ screen }: { screen: StudioScreen }) {
    const { t } = useLanguage();
    const Icon = screen.icon;
    return (
        <NavLink to={screen.path} className={railLinkClass}>
            <Icon size={17} strokeWidth={ICON_STROKE} />
            <span>{t(screen.label)}</span>
        </NavLink>
    );
}

/** The system mark, which also takes you home. */
function HomeMark({ tone }: { tone: 'rail' | 'header' }) {
    const { t } = useLanguage();
    return (
        <NavLink to={STUDIO_HOME} title={t('shell.home')} aria-label={t('shell.home')}
            className={`rounded-md p-0.5 ${tone === 'rail' ? 'hover:bg-[var(--studio-rail-active)]' : 'hover:bg-[var(--studio-accent-soft)]'}`}>
            <AppMark size={24} />
        </NavLink>
    );
}

function Rail({ current, collapsed, onCollapse }: { current?: StudioScreen; collapsed: boolean; onCollapse: () => void }) {
    const { user } = useAuth();
    const { t } = useLanguage();
    const [openGroups, setOpenGroups] = useState(readOpenGroups);
    const toggle = (id: string) => {
        const next = openGroups.includes(id) ? openGroups.filter((open) => open !== id) : [...openGroups, id];
        setOpenGroups(next);
        try {
            localStorage.setItem(RAIL_OPEN_KEY, JSON.stringify(next));
        } catch {
            // The rail still works; it just forgets on reload.
        }
    };
    return (
        // The fixed-width inner column keeps the contents still while the rail slides shut.
        <aside inert={collapsed}
            className={`studio-rail flex-shrink-0 overflow-hidden bg-[var(--studio-rail)] text-[var(--studio-rail-text)] transition-[width] duration-200 ${collapsed ? 'w-0' : 'w-60'}`}>
            <div className="flex h-full w-60 flex-col">
                <div className="flex h-14 flex-shrink-0 items-center gap-1 px-3">
                    <HomeMark tone="rail" />
                    <button type="button" onClick={onCollapse} title={t('shell.collapse')} aria-label={t('shell.collapse')} className={railIconClass}>
                        <PanelLeftClose size={16} strokeWidth={ICON_STROKE} />
                    </button>
                    <div className="flex-1" />
                    <NotificationBell buttonClass={railIconClass} />
                </div>
                <nav className="flex-1 overflow-y-auto pb-4 pt-1">
                    {STUDIO_GROUPS.map((group) => {
                        const open = !group.collapsible || openGroups.includes(group.id);
                        // A closed group still shows the screen you are on, so the rail never loses your place.
                        const screens = open ? group.screens : group.screens.filter((screen) => screen === current);
                        return (
                            <div key={group.id} className="mb-4 space-y-0.5">
                                {group.label && (group.collapsible ? (
                                    <button
                                        type="button"
                                        onClick={() => toggle(group.id)}
                                        aria-expanded={open}
                                        className="flex w-full items-center gap-1 px-4 pb-1.5 text-left text-[11px] font-medium tracking-[0.08em] text-[var(--studio-rail-group)] hover:text-[var(--studio-rail-text)]"
                                    >
                                        <ChevronRight size={12} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
                                        {t(group.label)}
                                    </button>
                                ) : (
                                    <p className="px-5 pb-1.5 text-[11px] font-medium tracking-[0.08em] text-[var(--studio-rail-group)]">
                                        {t(group.label)}
                                    </p>
                                ))}
                                {screens.map((screen) => <RailLink key={screen.path} screen={screen} />)}
                            </div>
                        );
                    })}
                </nav>
                {/* Settings sits at the bottom of the rail, as decided for the rebuild. */}
                <div className="border-t border-white/10 py-3">
                    <NavLink to={SETTINGS_PATH} className={railLinkClass}>
                        <SettingsIcon size={17} strokeWidth={ICON_STROKE} />
                        <span className="flex-1 text-left">{t('settings.title')}{user?.name && <span className="mt-0.5 block text-xs opacity-70">{user.name}</span>}</span>
                    </NavLink>
                </div>
            </div>
        </aside>
    );
}

export default function StudioLayout() {
    const screen = useCurrentScreen();
    const { pathname } = useLocation();
    const { t, language } = useLanguage();
    const { logout } = useAuth();
    const { clientId } = useClient();
    const [collapsed, setCollapsed] = useState(readCollapsed);
    const title = pathname.startsWith('/record/') ? t('shell.editTransaction')
        : t(screen?.label ?? (pathname === '/record' ? 'shell.record' : 'settings.title'));

    useEffect(() => {
        try {
            localStorage.setItem(RAIL_COLLAPSED_KEY, collapsed ? '1' : '0');
        } catch {
            // The rail opens again on reload.
        }
    }, [collapsed]);

    // Ctrl+\ (⌘+\ on a Mac) opens and closes the rail, as in Notion.
    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key === '\\') {
                event.preventDefault();
                setCollapsed((value) => !value);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    return (
        <div lang={language} className="studio-root flex h-screen min-h-0 overflow-hidden bg-[var(--studio-bg)] text-[var(--studio-text)]">
            <ConfirmProvider>
            {/* Keyed by client: notifications belong to one client and must not carry over. */}
            <NotificationsProvider key={clientId ?? 'none'}>
            <Rail current={screen} collapsed={collapsed} onCollapse={() => setCollapsed(true)} />
            <div className="studio-content flex min-w-0 flex-1 flex-col">
                <header className="studio-header flex h-14 flex-shrink-0 items-center gap-3 border-b border-[var(--studio-border)] bg-[var(--studio-surface)] px-6">
                    {/* With the rail shut, its top row moves here, in the same order. */}
                    {collapsed && (
                        <div className="-ml-3 flex items-center gap-1 border-r border-[var(--studio-border)] pr-3">
                            <HomeMark tone="header" />
                            <button type="button" onClick={() => setCollapsed(false)} title={t('shell.expand')} aria-label={t('shell.expand')} className={headerIconClass}>
                                <PanelLeftOpen size={16} strokeWidth={ICON_STROKE} />
                            </button>
                            <NotificationBell buttonClass={headerIconClass} />
                        </div>
                    )}
                    <div className="min-w-0">
                        {screen?.section && <p className="text-[11px] text-[var(--studio-text-faint)]">{t(screen.section)}</p>}
                        <h1 className="truncate text-sm font-semibold">{title}</h1>
                    </div>
                    <div className="flex-1" />
                    <NavLink
                        to="/record"
                        className="rounded-md bg-[var(--studio-accent)] px-3 py-2 text-xs font-medium text-[var(--studio-accent-text)] transition-opacity hover:opacity-90"
                    >
                        {t('shell.record')}
                    </NavLink>
                    <button
                        onClick={logout}
                        className={headerIconClass}
                        title={t('shell.signOut')}
                        aria-label={t('shell.signOut')}
                    >
                        <LogOut size={16} strokeWidth={ICON_STROKE} />
                    </button>
                </header>
                <main className="studio-main min-h-0 flex-1 overflow-auto p-6">
                    <Outlet />
                </main>
            </div>
            </NotificationsProvider>
            </ConfirmProvider>
        </div>
    );
}
