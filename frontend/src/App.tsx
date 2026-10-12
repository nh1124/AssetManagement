import './index.css';
import { ToastProvider } from './components/Toast';
import { ClientProvider } from './context/ClientContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './pages/Login';
import DesktopApp from './desktop/DesktopApp';
import MobileApp from './mobile/MobileApp';
import StudioApp from './studio/StudioApp';
import { useShellMode } from './shared/useShellMode';

/* The rebuilt desktop UI runs alongside the old one under /studio until its
 * core screens are done. Nothing else changes until the default moves, so the
 * stack keeps working through the rebuild. The mobile shell is out of scope and
 * keeps its own path. */
const isStudio = () => window.location.pathname.startsWith('/studio');

function AppContent() {
  const { isAuthenticated, isLoading } = useAuth();
  const shellMode = useShellMode();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  if (isStudio()) {
    return (
      <ClientProvider>
        <ToastProvider>
          <StudioApp />
        </ToastProvider>
      </ClientProvider>
    );
  }

  return (
    <ClientProvider>
      <ToastProvider>
        {shellMode === 'mobile' ? <MobileApp /> : <DesktopApp />}
      </ToastProvider>
    </ClientProvider>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

export default App;
