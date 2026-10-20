import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import NotificationsProvider from '../studio/components/NotificationsProvider';
import { useClient } from '../context/ClientContext';
import Layout from './components/Layout';
import MobileConfirm from './components/MobileConfirm';
import SnackProvider from './components/SnackProvider';
import Approvals from './pages/Approvals';
import Assets from './pages/Assets';
import Earmarks from './pages/Earmarks';
import Goals from './pages/Goals';
import Home from './pages/Home';
import Ledger from './pages/Ledger';
import More from './pages/More';
import Notifications from './pages/Notifications';
import Plan from './pages/Plan';
import Settings from './pages/Settings';
import '../studio/theme.css';
import './mobile.css';

/** The mobile app (WP25): the studio's data and words in a phone's shape. Paths are the studio's without /studio,
 * so a notification's link opens the same screen here. */
export default function MobileApp() {
    const { clientId } = useClient();
    return <div className="mobile-root studio-root min-h-dvh bg-[var(--studio-bg)] text-[var(--studio-text)]">
        <BrowserRouter>
            {/* One provider per client, so a switch never shows the previous client's list or confirmation. */}
            <NotificationsProvider key={clientId}>
                <SnackProvider>
                    <MobileConfirm>
                        <Routes>
                            <Route element={<Layout />}>
                                <Route index element={<Home />} />
                                <Route path="ledger" element={<Ledger />} />
                                <Route path="plan" element={<Plan />} />
                                <Route path="goals" element={<Goals />} />
                                <Route path="more" element={<More />} />
                                {/* Not /assets: the built bundle lives there and the web server answers it as a folder. */}
                                <Route path="accounts" element={<Assets />} />
                                <Route path="earmarks" element={<Earmarks />} />
                                <Route path="approvals" element={<Approvals />} />
                                <Route path="notifications" element={<Notifications />} />
                                <Route path="settings" element={<Settings />} />
                                <Route path="*" element={<Navigate to="/" replace />} />
                            </Route>
                        </Routes>
                    </MobileConfirm>
                </SnackProvider>
            </NotificationsProvider>
        </BrowserRouter>
    </div>;
}
