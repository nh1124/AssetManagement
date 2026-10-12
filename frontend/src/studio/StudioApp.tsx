import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import StudioLayout from './components/StudioLayout';
import ScreenTabs from './components/ScreenTabs';
import Pending from './components/Pending';
import Record from './pages/Record';
import Overview from './pages/assets/Overview';
import Accounts from './pages/assets/Accounts';
import Earmarks from './pages/assets/Earmarks';
import Ledger from './pages/ledger/Ledger';
import Flows from './pages/Flows';
import Ai from './pages/automation/Ai';
import Approvals from './pages/automation/Approvals';
import Audit from './pages/automation/Audit';
import DataHealth from './pages/debug/DataHealth';
import DatabaseAccounts from './pages/db/Accounts';
import Fx from './pages/db/Fx';
import Definitions from './pages/db/Definitions';
import Products from './pages/db/Products';
import Settings from './pages/Settings';
import { SETTINGS_PATH, STUDIO_HOME, STUDIO_SCREENS, type StudioScreen } from './navigation';
import './theme.css';

/** Screens a wave has built, by path and then by tab segment.
 *
 * Everything absent still routes and renders its note below, so adding a screen
 * is one entry here rather than another branch in the route tree.
 */
const BUILT: Record<string, { index: ReactElement; tabs?: Record<string, ReactElement> }> = {
    ledger: {
        index: <Ledger />,
        tabs: { unmatched: <Ledger unmatched /> },
    },
    flows: { index: <Flows /> },
    assets: {
        index: <Overview />,
        tabs: { accounts: <Accounts />, earmarks: <Earmarks /> },
    },
    'automation/ai': { index: <Ai /> },
    'automation/approvals': { index: <Approvals /> },
    'automation/audit': { index: <Audit /> },
    'debug/data-health': { index: <DataHealth /> },
    'db/accounts': { index: <DatabaseAccounts /> },
    'db/fx': { index: <Fx /> },
    'db/definitions': {
        index: <Definitions />,
        tabs: { income: <Definitions tab="income" />, repayment: <Definitions tab="repayment" />, allocation: <Definitions tab="allocation" /> },
    },
    'db/fixed-assets': { index: <Products assets /> },
    'db/consumables': { index: <Products assets={false} /> },
    [SETTINGS_PATH]: { index: <Settings /> },
};

/** What each unbuilt screen will hold, and which wave fills it. */
const PENDING_NOTES: Record<string, { wave: string; note: string }> = {
    ledger: { wave: 'W2', note: '記録の一覧、未照合（取引の提案）、予算との対応。' },
    flows: { wave: 'W2', note: '対象月の収入と支出を分類ごとに。' },
    budget: { wave: 'W4', note: '月末計画と照合済み実績の差、行動の記録。' },
    goals: { wave: 'W5', note: '資産推移、ゴール案の比較と切り替え。' },
};

function PendingScreen({ screen }: { screen: StudioScreen }) {
    const { pathname } = useLocation();
    const pending = PENDING_NOTES[screen.path];
    const tab = screen.tabs?.find((candidate) => {
        const full = candidate.segment ? `/${screen.path}/${candidate.segment}` : `/${screen.path}`;
        return pathname.replace(/\/+$/, '') === full;
    });
    return (
        <Pending wave={pending?.wave ?? '未割当'}>
            {pending?.note}
            {tab?.segment ? `（${tab.label}）` : null}
        </Pending>
    );
}

export default function StudioApp() {
    return (
        <BrowserRouter basename="/studio">
            <Routes>
                <Route element={<StudioLayout />}>
                    <Route index element={<Navigate to={STUDIO_HOME} replace />} />
                    <Route path="record" element={<Record />} />
                    {STUDIO_SCREENS.map((screen) => {
                        const built = BUILT[screen.path];
                        return (
                            <Route
                                key={screen.path}
                                path={screen.path}
                                element={<><ScreenTabs screen={screen} /><Outlet /></>}
                            >
                                <Route
                                    index
                                    element={built?.index ?? <PendingScreen screen={screen} />}
                                />
                                {screen.tabs
                                    ?.filter((tab) => tab.segment)
                                    .map((tab) => (
                                        <Route
                                            key={tab.segment}
                                            path={tab.segment}
                                            element={
                                                built?.tabs?.[tab.segment] ?? <PendingScreen screen={screen} />
                                            }
                                        />
                                    ))}
                            </Route>
                        );
                    })}
                    <Route
                        path={SETTINGS_PATH}
                        element={BUILT[SETTINGS_PATH].index}
                    />
                    <Route path="*" element={<Navigate to={STUDIO_HOME} replace />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}
