import { NavLink } from 'react-router-dom';
import type { StudioScreen } from '../navigation';

/** Tabs are links, not state: each one is a URL you can reload and go back to. */
export default function ScreenTabs({ screen }: { screen: StudioScreen }) {
    if (!screen.tabs?.length) return null;
    return (
        <div className="mb-4 inline-flex gap-1 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-1">
            {screen.tabs.map((tab) => (
                <NavLink
                    key={tab.segment || 'index'}
                    to={tab.segment ? `/${screen.path}/${tab.segment}` : `/${screen.path}`}
                    end={!tab.segment}
                    className={({ isActive }) =>
                        `rounded-md px-3 py-1.5 text-xs transition-colors ${
                            isActive
                                ? 'bg-[var(--studio-accent-soft)] font-medium text-[var(--studio-accent)]'
                                : 'text-[var(--studio-text-muted)] hover:text-[var(--studio-text)]'
                        }`
                    }
                >
                    {tab.label}
                </NavLink>
            ))}
        </div>
    );
}
