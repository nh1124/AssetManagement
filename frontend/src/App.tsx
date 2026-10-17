import './index.css';
import { useEffect } from 'react';
import { ToastProvider } from './components/Toast';
import { ClientProvider } from './context/ClientContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './pages/Login';
import MobileApp from './mobile/MobileApp';
import StudioApp from './studio/StudioApp';
import { useShellMode } from './shared/useShellMode';

/* The desktop web UI is the rebuilt studio under /studio; the old desktop UI is
 * gone. The mobile shell keeps its own path until a new one is built on the
 * studio's screens. */
const isStudio = () => window.location.pathname.startsWith('/studio');

function ToStudio() {
  useEffect(() => { window.location.replace('/studio'); }, []);
  return null;
}

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
        {shellMode === 'mobile' ? <MobileApp /> : <ToStudio />}
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
