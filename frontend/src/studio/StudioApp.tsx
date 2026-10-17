import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import StudioLayout from './components/StudioLayout';
import ScreenTabs from './components/ScreenTabs';
import Record from './pages/Record';
import Overview from './pages/assets/Overview';
import Assets from './pages/assets/Assets';
import Accounts from './pages/assets/Accounts';
import Earmarks from './pages/assets/Earmarks';
import Ledger from './pages/ledger/Ledger';
import Flows from './pages/Flows';
import Budget from './pages/budget/Budget';
import Actions from './pages/budget/Actions';
import Trends from './pages/report/Trends';
import Breakdown from './pages/report/Monthly';
import Review from './pages/report/Review';
import Export from './pages/report/Export';
import LifeEventList from './pages/goals/LifeEventList';
import GoalSummary from './pages/goals/GoalSummary';
import GoalPage from './pages/goals/GoalPage';
import GoalWorkspace from './pages/goals/GoalWorkspace';
import LifeEventGraph from './pages/goals/LifeEventGraph';
import ScenarioLayout from './pages/goals/ScenarioLayout';
import ScenarioList from './pages/goals/ScenarioList';
import Comparison from './pages/goals/Comparison';
import Simulation from './pages/goals/Simulation';
import Ai from './pages/automation/Ai';
import Approvals from './pages/automation/Approvals';
import Audit from './pages/automation/Audit';
import DataHealth from './pages/debug/DataHealth';
import DatabaseAccounts from './pages/db/Accounts';
import Fx from './pages/db/Fx';
import Definitions from './pages/db/Definitions';
import Products from './pages/db/Products';
import Settings from './pages/Settings';
import { SETTINGS_PATH, STUDIO_EDITOR_PATHS, STUDIO_HOME, STUDIO_SCREENS } from './navigation';
import './theme.css';

/** Every screen, by path and then by tab segment.
 *
 * Adding a screen is one entry here plus one in navigation.ts, rather than
 * another branch in the route tree.
 */
const SCREENS: Record<string, { index: ReactElement; tabs?: Record<string, ReactElement>; layout?: ReactElement }> = {
    ledger: {
        index: <Ledger />,
        tabs: { unmatched: <Ledger unmatched /> },
    },
    flows: { index: <Flows />, tabs: { accounts: <Flows subjects /> } },
    budget: { index: <Budget />, tabs: { actions: <Actions /> } },
    report: { index: <Trends />, tabs: { breakdown: <Breakdown />, review: <Review />, export: <Export /> } },
    goals: { index: <GoalSummary /> },
    assets: {
        layout: <Assets />,
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
                        <Route path="events/:goalId" element={<GoalWorkspace />} />
                        <Route path="events/new" element={<GoalPage />} />
                        <Route path="events/:goalId/edit" element={<GoalPage />} />
                    </Route>
                    <Route path="goals/events" element={<Navigate to="/goals/scenarios" replace />} />
                    <Route path="goals/graph" element={<Navigate to="/goals/scenarios" replace />} />
                    <Route path="goals/simulation" element={<Navigate to="/goals/scenarios" replace />} />
                    <Route path={STUDIO_EDITOR_PATHS.newGoal} element={<GoalPage />} />
                    <Route path={STUDIO_EDITOR_PATHS.editGoal} element={<GoalPage />} />
                    <Route path="goals/events/:goalId" element={<GoalWorkspace />} />
                    {STUDIO_SCREENS.map((screen) => {
                        const screenRoutes = SCREENS[screen.path];
                        return (
                            <Route
                                key={screen.path}
                                path={screen.path}
                                element={<><ScreenTabs screen={screen} />{screenRoutes.layout ?? <Outlet />}</>}
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
