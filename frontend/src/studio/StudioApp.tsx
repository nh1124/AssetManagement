import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import StudioLayout from './components/StudioLayout';
import ScreenTabs from './components/ScreenTabs';
import Record from './pages/Record';
import Overview from './pages/assets/Overview';
import Accounts from './pages/assets/Accounts';
import Earmarks from './pages/assets/Earmarks';
import Ledger from './pages/ledger/Ledger';
import Flows from './pages/Flows';
import Budget from './pages/budget/Budget';
import Actions from './pages/budget/Actions';
import Goals from './pages/goals/Goals';
import Ai from './pages/automation/Ai';
import Approvals from './pages/automation/Approvals';
import Audit from './pages/automation/Audit';
import DataHealth from './pages/debug/DataHealth';
import DatabaseAccounts from './pages/db/Accounts';
import Fx from './pages/db/Fx';
import Definitions from './pages/db/Definitions';
import Products from './pages/db/Products';
import Settings from './pages/Settings';
import { SETTINGS_PATH, STUDIO_HOME, STUDIO_SCREENS } from './navigation';
import './theme.css';

/** Every screen, by path and then by tab segment.
 *
 * Adding a screen is one entry here plus one in navigation.ts, rather than
 * another branch in the route tree.
 */
const SCREENS: Record<string, { index: ReactElement; tabs?: Record<string, ReactElement> }> = {
    ledger: {
        index: <Ledger />,
        tabs: { unmatched: <Ledger unmatched /> },
    },
    flows: { index: <Flows /> },
    budget: { index: <Budget />, tabs: { actions: <Actions /> } },
    goals: { index: <Goals /> },
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
export default function StudioApp() {
    return (
        <BrowserRouter basename="/studio">
            <Routes>
                <Route element={<StudioLayout />}>
                    <Route index element={<Navigate to={STUDIO_HOME} replace />} />
                    <Route path="record" element={<Record />} />
                    {STUDIO_SCREENS.map((screen) => {
                        const screenRoutes = SCREENS[screen.path];
                        return (
                            <Route
                                key={screen.path}
                                path={screen.path}
                                element={<><ScreenTabs screen={screen} /><Outlet /></>}
                            >
                                <Route index element={screenRoutes.index} />
                                {screen.tabs
                                    ?.filter((tab) => tab.segment)
                                    .map((tab) => (
                                        <Route
                                            key={tab.segment}
                                            path={tab.segment}
                                            element={screenRoutes.tabs?.[tab.segment] ?? screenRoutes.index}
                                        />
                                    ))}
                            </Route>
                        );
                    })}
                    <Route
                        path={SETTINGS_PATH}
                        element={SCREENS[SETTINGS_PATH].index}
                    />
                    <Route path="*" element={<Navigate to={STUDIO_HOME} replace />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}
