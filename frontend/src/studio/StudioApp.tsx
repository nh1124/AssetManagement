import type { ReactElement } from 'react';
import { BrowserRouter, useParams, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import StudioLayout from './components/StudioLayout';
import ScreenTabs from './components/ScreenTabs';
import Record from './pages/Record';
import Overview from './pages/assets/Overview';
import Accounts from './pages/assets/Accounts';
import Earmarks from './pages/earmarks/Earmarks';
import Ledger from './pages/ledger/Ledger';
import Flows from './pages/Flows';
import Plan from './pages/plan/Plan';
import Trends from './pages/report/Trends';
import Breakdown from './pages/report/Monthly';
import Review from './pages/report/Review';
import Export from './pages/report/Export';
import LifeEventList from './pages/goals/LifeEventList';
import GoalSummary from './pages/goals/GoalSummary';
import LifeEventGraph from './pages/goals/LifeEventGraph';
import ScenarioLayout from './pages/goals/ScenarioLayout';
import ScenarioList from './pages/goals/ScenarioList';
import Comparison from './pages/goals/Comparison';
import Simulation from './pages/goals/Simulation';
import Ai from './pages/automation/Ai';
import Approvals from './pages/automation/Approvals';
import Connections from './pages/automation/Connections';
import Audit from './pages/automation/Audit';
import DatabaseAccounts from './pages/db/Accounts';
import Fx from './pages/db/Fx';
import AutoTransactions from './pages/db/AutoTransactions';
import Products from './pages/db/Products';
import Settings from './pages/Settings';
import { SETTINGS_PATH, STUDIO_EDITOR_PATHS, STUDIO_HOME, STUDIO_SCREENS } from './navigation';
import './theme.css';

/** Every screen, by path and then by tab segment.
 *
 * Adding a screen is one entry here plus one in navigation.ts, rather than
 * another branch in the route tree.
 */
const SCREENS: Record<string, { index: ReactElement; tabs?: Record<string, ReactElement> }> = {
    ledger: {
        index: <Ledger />,
        tabs: { auto: <Ledger automatic /> },
    },
    flows: { index: <Flows />, tabs: { accounts: <Flows subjects /> } },
    plan: { index: <Plan />, tabs: { earmarks: <Plan view="earmarks" />, auto: <Plan view="auto" /> } },
    report: { index: <Trends />, tabs: { breakdown: <Breakdown />, review: <Review />, export: <Export /> } },
    goals: { index: <GoalSummary /> },
    assets: {
        index: <Overview />,
        tabs: { accounts: <Accounts /> },
    },
    'automation/ai': { index: <Ai /> },
    'automation/connections': { index: <Connections /> },
    'automation/approvals': { index: <Approvals /> },
    'automation/audit': { index: <Audit /> },
    'db/accounts': { index: <DatabaseAccounts /> },
    'db/fx': { index: <Fx /> },
    'db/auto-transactions': {
        index: <AutoTransactions />,
        tabs: {
            income: <AutoTransactions tab="income" />, repayment: <AutoTransactions tab="repayment" />,
            allocation: <AutoTransactions tab="allocation" />,
        },
    },
    'db/fixed-assets': { index: <Products assets /> },
    'db/consumables': { index: <Products assets={false} /> },
    'db/earmarks': { index: <Earmarks /> },
    [SETTINGS_PATH]: { index: <Settings /> },
};

/** What each unbuilt screen will hold, and which wave fills it. */
export default function StudioApp() {
    return (
        <BrowserRouter basename="/studio">
            <Routes>
                <Route element={<StudioLayout />}>
                    <Route index element={<Navigate to={STUDIO_HOME} replace />} />
                    <Route path={STUDIO_EDITOR_PATHS.record} element={<Record />} />
                    {/* Editors have URLs without becoming destinations in the rail. */}
                    <Route path={STUDIO_EDITOR_PATHS.transaction} element={<Record />} />
                    <Route path="goals/scenarios" element={<ScenarioList />} />
                    <Route path="goals/compare" element={<Comparison />} />
                    <Route path="goals/scenarios/:scenarioId" element={<ScenarioLayout />}>
                        <Route index element={<Navigate to="events" replace />} />
                        <Route path="events" element={<LifeEventList />} />
                        <Route path="graph" element={<LifeEventGraph />} />
                        <Route path="simulation" element={<Simulation />} />
                        {/* Events open in an overlay on the list; their old pages have no screen. */}
                        <Route path="events/*" element={<Navigate to="../events" replace />} />
                    </Route>
                    <Route path="goals/events" element={<Navigate to="/goals/scenarios" replace />} />
                    <Route path="goals/graph" element={<Navigate to="/goals/scenarios" replace />} />
                    <Route path="goals/simulation" element={<Navigate to="/goals/scenarios" replace />} />
                    {/* Events live inside a scenario now; flat event URLs have no scenario to edit. */}
                    <Route path="goals/events/*" element={<Navigate to="/goals/scenarios" replace />} />
                    {/* Earmarks left the assets tabs for their own database screen (U4). */}
                    <Route path="db/definitions" element={<Navigate to="/db/auto-transactions" replace />} />
                    <Route path="db/definitions/:tab" element={<LegacyAutoTransactionRedirect />} />
                    <Route path="ledger/unmatched" element={<Navigate to="/ledger/auto" replace />} />
                    <Route path="assets/earmarks" element={<Navigate to="/db/earmarks" replace />} />
                    {/* 予算 became 計画 (WP16). */}
                    <Route path="budget" element={<Navigate to="/plan" replace />} />
                    <Route path="budget/actions" element={<Navigate to="/plan" replace />} />
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

function LegacyAutoTransactionRedirect() { const { tab } = useParams(); return <Navigate to={`/db/auto-transactions/${tab ?? ""}`} replace />; }
