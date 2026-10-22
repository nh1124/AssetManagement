import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import AppMark from '../studio/components/AppMark';
import { setActiveLanguage, tr, type Language } from '../studio/i18n';
import { ApiError, createAdminConnection } from './api';
import { AdminContext, useAdmin } from './context';
import type { Me, SignInResult } from './types';
import { Loading, Notice } from './ui';
import { useAction } from './hooks';
import SignIn from './SignIn';
import StepUp from './StepUp';
import Overview from './Overview';
import Accounts, { AccountDetail } from './Accounts';
import Admins from './Admins';
import Settings from './Settings';
import Audit from './Audit';
import MyAccount from './MyAccount';

const storageKey = 'admin.ui.language';
function initialLanguage(): Language {
    try {
        const stored = localStorage.getItem(storageKey);
        if (stored === 'ja' || stored === 'en') return stored;
    } catch { /* Storage can be disabled. */ }
    return navigator.language.toLowerCase().startsWith('ja') ? 'ja' : 'en';
}
function home(me: Me) { return me.permissions.includes('accounts.read') ? '/overview' : '/me'; }
function Gate({ permission, children }: { permission: string; children: ReactNode }) {
    const { can } = useAdmin();
    return can(permission) ? children : <p role="alert">{tr('この画面を見る権限がありません。', 'You do not have permission to view this page.')}</p>;
}
function Workspace({ onLogout, children }: { onLogout: () => Promise<void>; children: ReactNode }) {
    const { me, can } = useAdmin();
    const action = useAction();
    const links = [
        ['/overview', tr('概要', 'Overview'), 'accounts.read'], ['/accounts', tr('アカウント', 'Accounts'), 'accounts.read'],
        ['/admins', tr('管理者', 'Administrators'), 'admins.manage'], ['/settings', tr('システム設定', 'System settings'), 'settings.manage'],
        ['/audit', tr('監査ログ', 'Audit log'), 'audit.read'],
    ];
    return <div className="admin-shell"><aside className="admin-rail">
        <Link className="admin-brand" to={home(me)}><AppMark size={32} /><span>{tr('管理', 'Admin')}</span></Link>
        <nav aria-label={tr('管理メニュー', 'Administration')}>{links.filter(([, , permission]) => can(permission)).map(([path, label]) => <NavLink to={path} key={path}>{label}</NavLink>)}</nav>
        <NavLink to="/me" className="admin-profile-link">{tr('自分のアカウント', 'My account')}</NavLink>
    </aside><div className="admin-workspace"><header className="admin-header"><Link to="/me">{me.username}</Link><span className="admin-header-spacer" />{children}<button disabled={action.busy} onClick={() => void action.run(onLogout, '')}>{tr('サインアウト', 'Sign out')}</button></header>
        <main id="admin-main" tabIndex={-1}><Notice error={action.error} /><Routes>
            <Route path="/overview" element={<Gate permission="accounts.read"><Overview /></Gate>} />
            <Route path="/accounts" element={<Gate permission="accounts.read"><Accounts /></Gate>} />
            <Route path="/accounts/:id" element={<Gate permission="accounts.read"><AccountDetail /></Gate>} />
            <Route path="/admins" element={<Gate permission="admins.manage"><Admins /></Gate>} />
            <Route path="/settings" element={<Gate permission="settings.manage"><Settings /></Gate>} />
            <Route path="/audit" element={<Gate permission="audit.read"><Audit /></Gate>} />
            <Route path="/me" element={<MyAccount />} />
            <Route path="*" element={<Navigate to={home(me)} replace />} />
        </Routes></main>
    </div></div>;
}

/** Client-independent language boundary. Auth/staged cookies survive language remounts. */
export default function AdminApp() {
    const navigate = useNavigate();
    const [language, setLanguage] = useState(initialLanguage);
    const [me, setMe] = useState<Me | null>(null);
    const [stage, setStage] = useState<SignInResult | null>(null);
    const [notice, setNotice] = useState('');
    const [booting, setBooting] = useState(true);
    const [bootError, setBootError] = useState('');
    const [bootRevision, setBootRevision] = useState(0);
    const [stepUpOpen, setStepUpOpen] = useState(false);
    setActiveLanguage(language);
    useEffect(() => {
        document.documentElement.lang = language;
        document.title = tr('AssetManagement 管理', 'AssetManagement Admin');
        try { localStorage.setItem(storageKey, language); } catch { /* Use memory when storage is disabled. */ }
    }, [language]);
    const { api, finishStepUp } = useMemo(() => createAdminConnection({
        unauthorized: detail => {
            setMe(null); setStage(null);
            setNotice(`${tr('セッションが切れました。もう一度サインインしてください。', 'Your session ended. Sign in again.')} ${detail}`);
        },
        showStepUp: setStepUpOpen,
    }), []);
    useEffect(() => {
        let stale = false;
        void api.request<Me>('/me', { authenticate: false }).then(result => { if (!stale) { setMe(result); setBootError(''); } }).catch((error: unknown) => {
            if (!stale && !(error instanceof ApiError && error.status === 401)) setBootError(error instanceof Error ? error.message : tr('接続できませんでした。', 'Could not connect.'));
        }).finally(() => { if (!stale) { setBooting(false); } });
        return () => { stale = true; };
    }, [api, bootRevision]);
    async function refreshMe() { setMe(await api.get<Me>('/me')); }
    async function signedIn() {
        const result = await api.get<Me>('/me');
        setMe(result); setStage(null); setNotice(''); navigate(home(result), { replace: true });
    }
    const languageToggle = <div className="admin-language" role="group" aria-label={tr('言語', 'Language')}>
        <button lang="ja" aria-pressed={language === 'ja'} onClick={() => setLanguage('ja')}>{tr('日本語', '日本語')}</button>
        <button lang="en" aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>{tr('English', 'English')}</button>
    </div>;
    return <div className="studio-root admin-root"><Fragment key={language}>
        <div className="admin-band">{tr('管理コンソール（この端末だけ）', 'Admin console (this device only)')}</div>
        {booting ? <Loading /> : bootError ? <section className="admin-card"><Notice error={bootError} /><button onClick={() => { setBooting(true); setBootError(''); setBootRevision(value => value + 1); }}>{tr('再接続', 'Reconnect')}</button></section> : me ? <AdminContext.Provider value={{ api, me, refreshMe }}>
            <a className="admin-skip" href="#admin-main">{tr('本文へ', 'Skip to content')}</a>
            <Workspace onLogout={async () => { await api.delete('/session'); setMe(null); setStage(null); setNotice(tr('サインアウトしました。', 'Signed out.')); navigate('/', { replace: true }); }}>{languageToggle}</Workspace>
        </AdminContext.Provider> : <><header className="admin-public-header">{languageToggle}</header><SignIn api={api} stage={stage} onStage={setStage} onSignedIn={signedIn} notice={notice} /></>}
        {stepUpOpen && <StepUp api={api} onSuccess={() => finishStepUp()} onCancel={() => finishStepUp(true)} />}
    </Fragment></div>;
}
