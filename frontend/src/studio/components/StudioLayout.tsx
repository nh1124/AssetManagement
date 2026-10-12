import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { LogOut, Settings as SettingsIcon } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { SETTINGS_PATH, STUDIO_GROUPS, STUDIO_SCREENS } from '../navigation';

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

function Rail() {
    const { user } = useAuth();
    return (
        <aside className="flex w-60 flex-shrink-0 flex-col bg-[var(--studio-rail)] text-[var(--studio-rail-text)]">
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
                    FINANCIAL STUDIO
                </p>
            </div>

            <nav className="flex-1 overflow-y-auto pb-4">
                {STUDIO_GROUPS.map((group) => (
                    <div key={group.id} className="mb-4">
                        {group.label && (
                            <p className="px-5 pb-2 text-[10px] font-medium tracking-[0.16em] text-[var(--studio-rail-group)]">
                                {group.label}
                            </p>
                        )}
                        {group.screens.map((screen) => {
                            const Icon = screen.icon;
                            return (
                                <NavLink
                                    key={screen.path}
                                    to={screen.path}
                                    className={({ isActive }) =>
                                        `flex items-center gap-3 px-5 py-2 text-sm transition-colors ${
                                            isActive
                                                ? 'bg-[var(--studio-rail-active)] text-[var(--studio-rail-text-strong)]'
                                                : 'hover:bg-[var(--studio-rail-active)]/50'
                                        }`
                                    }
                                >
                                    <Icon size={16} />
                                    <span>{screen.label}</span>
                                </NavLink>
                            );
                        })}
                    </div>
                ))}
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
                    <span className="flex-1 text-left">{user?.name || '設定'}</span>
                </NavLink>
            </div>
        </aside>
    );
}

export default function StudioLayout() {
    const screen = useCurrentScreen();
    const { logout } = useAuth();

    return (
        <div className="studio-root flex h-screen min-h-0 overflow-hidden bg-[var(--studio-bg)] text-[var(--studio-text)]">
            <Rail />
            <div className="flex min-w-0 flex-1 flex-col">
                <header className="flex h-14 flex-shrink-0 items-center gap-3 border-b border-[var(--studio-border)] bg-[var(--studio-surface)] px-6">
                    <div className="min-w-0">
                        <p className="text-[11px] text-[var(--studio-text-faint)]">
                            {screen?.section ?? ''}
                        </p>
                        <h1 className="truncate text-sm font-semibold">{screen?.label ?? '設定'}</h1>
                    </div>
                    <div className="flex-1" />
                    <button
                        onClick={logout}
                        className="rounded p-2 text-[var(--studio-text-muted)] transition-colors hover:bg-[var(--studio-accent-soft)] hover:text-[var(--studio-text)]"
                        title="サインアウト"
                    >
                        <LogOut size={16} />
                    </button>
                </header>
                <main className="min-h-0 flex-1 overflow-auto p-6">
                    <Outlet />
                </main>
            </div>
        </div>
    );
}
