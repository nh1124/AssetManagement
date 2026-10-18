import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useState } from 'react';
import { ChevronRight, LogOut, Settings as SettingsIcon } from 'lucide-react';
import { useClient } from '../../context/ClientContext';
import NotificationBell from './NotificationBell';
import NotificationsProvider from './NotificationsProvider';
import { useLanguage } from '../i18n';
import { useAuth } from '../../context/AuthContext';
import { SETTINGS_PATH, STUDIO_GROUPS, STUDIO_SCREENS, type StudioScreen } from '../navigation';
import ConfirmProvider from './ConfirmProvider';

/** The screen whose path is the longest prefix of the current location.
 *
 * Longest wins so that "db/accounts" is not shadowed by a future "db", and a
 * tab route ("assets/earmarks") still resolves to its screen.
 */
function useCurrentScreen() {
    const { pathname } = useLocation();
    const here = pathname.replace(/^\/+|\/+$/g, '');
    return STUDIO_SCREENS
        .filter((screen) => here === screen.path || here.startsWith(`${screen.path}/`))
        .sort((a, b) => b.path.length - a.path.length)[0];
}

const RAIL_OPEN_KEY = 'studio.rail.open';

/** Ids of the collapsible groups the user opened. Storage may be unavailable. */
function readOpenGroups(): string[] {
    try {
        const stored: unknown = JSON.parse(localStorage.getItem(RAIL_OPEN_KEY) ?? '[]');
        return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : [];
    } catch {
        return [];
    }
}

const railLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-5 py-2 text-sm transition-colors ${
        isActive
            ? 'bg-[var(--studio-rail-active)] text-[var(--studio-rail-text-strong)]'
            : 'hover:bg-[var(--studio-rail-active)]/50'
    }`;

function RailLink({ screen }: { screen: StudioScreen }) {
    const { t } = useLanguage();
    const Icon = screen.icon;
    return (
        <NavLink to={screen.path} className={railLinkClass}>
            <Icon size={16} />
            <span>{t(screen.label)}</span>
        </NavLink>
    );
}

function Rail({ current }: { current?: StudioScreen }) {
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
    const offRail = STUDIO_GROUPS.filter((group) => group.offRail).flatMap((group) => group.screens);
    return (
        <aside className="studio-rail flex w-60 flex-shrink-0 flex-col bg-[var(--studio-rail)] text-[var(--studio-rail-text)]">
            <div className="px-5 pt-5 pb-6">
                <div className="flex items-center gap-2">
                    <span className="flex h-7 w-7 items-center justify-center rounded bg-[var(--studio-rail-active)] text-sm font-semibold text-[var(--studio-rail-text-strong)]">
                        a
                    </span>
                    <span className="text-sm font-semibold text-[var(--studio-rail-text-strong)]">
                        AssetManagement
                    </span>
                </div>
                <p className="mt-1 pl-9 text-[10px] tracking-[0.18em] text-[var(--studio-rail-group)]">
                    {t('shell.subtitle')}
                </p>
            </div>
            <nav className="flex-1 overflow-y-auto pb-4">
                {STUDIO_GROUPS.filter((group) => !group.offRail).map((group) => {
                    const open = !group.collapsible || openGroups.includes(group.id);
                    // A closed group still shows the screen you are on, so the rail never loses your place.
                    const screens = open ? group.screens : group.screens.filter((screen) => screen === current);
                    return (
                        <div key={group.id} className="mb-4">
                            {group.label && (group.collapsible ? (
                                <button
                                    type="button"
                                    onClick={() => toggle(group.id)}
                                    aria-expanded={open}
                                    className="flex w-full items-center gap-1 px-5 pb-2 text-left text-[10px] font-medium tracking-[0.16em] text-[var(--studio-rail-group)] hover:text-[var(--studio-rail-text)]"
                                >
                                    <ChevronRight size={12} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
                                    {t(group.label)}
                                </button>
                            ) : (
                                <p className="px-5 pb-2 text-[10px] font-medium tracking-[0.16em] text-[var(--studio-rail-group)]">
                                    {t(group.label)}
                                </p>
                            ))}
                            {screens.map((screen) => <RailLink key={screen.path} screen={screen} />)}
                        </div>
                    );
                })}
            </nav>
            {/* Settings sits at the bottom of the rail, as decided for the rebuild. */}
            <div className="border-t border-white/10 px-3 py-3">
                <NavLink
                    to={SETTINGS_PATH}
                    className={({ isActive }) =>
                        `flex items-center gap-3 rounded px-2 py-2 text-sm transition-colors ${
                            isActive
                                ? 'bg-[var(--studio-rail-active)] text-[var(--studio-rail-text-strong)]'
                                : 'hover:bg-[var(--studio-rail-active)]/50'
                        }`
                    }
                >
                    <SettingsIcon size={16} />
                    <span className="flex-1 text-left">{t('settings.title')}{user?.name && <span className="mt-1 block text-xs opacity-70">{user.name}</span>}</span>
                </NavLink>
                {offRail.map((screen) => (
                    <NavLink
                        key={screen.path}
                        to={screen.path}
                        className="mt-1 block px-2 text-[11px] text-[var(--studio-rail-group)] hover:text-[var(--studio-rail-text)]"
                    >
                        {t(screen.section)}：{t(screen.label)}
                    </NavLink>
                ))}
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

    return (
        <div lang={language} className="studio-root flex h-screen min-h-0 overflow-hidden bg-[var(--studio-bg)] text-[var(--studio-text)]">
            <ConfirmProvider>
            {/* Keyed by client: notifications belong to one client and must not carry over. */}
            <NotificationsProvider key={clientId ?? 'none'}>
            <Rail current={screen} />
            <div className="studio-content flex min-w-0 flex-1 flex-col">
                <header className="studio-header flex h-14 flex-shrink-0 items-center gap-3 border-b border-[var(--studio-border)] bg-[var(--studio-surface)] px-6">
                    <div className="min-w-0">
                        <p className="text-[11px] text-[var(--studio-text-faint)]">
                            {screen ? t(screen.section) : pathname.startsWith('/record') ? t('group.workspace') : ''}
                        </p>
                        <h1 className="truncate text-sm font-semibold">{pathname.startsWith('/record/') ? '取引を編集' : t(screen?.label ?? (pathname === '/record' ? 'shell.record' : 'settings.title'))}</h1>
                    </div>
                    <div className="flex-1" />
                    <NotificationBell />
                    <NavLink
                        to="/record"
                        className="rounded-md bg-[var(--studio-accent)] px-3 py-2 text-xs font-medium text-[var(--studio-accent-text)] transition-opacity hover:opacity-90"
                    >
                        {t('shell.record')}
                    </NavLink>
                    <button
                        onClick={logout}
                        className="rounded p-2 text-[var(--studio-text-muted)] transition-colors hover:bg-[var(--studio-accent-soft)] hover:text-[var(--studio-text)]"
                        title={t('shell.signOut')}
                        aria-label={t('shell.signOut')}
                    >
                        <LogOut size={16} />
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
