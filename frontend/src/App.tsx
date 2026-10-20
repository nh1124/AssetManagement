import './index.css';
import { useEffect } from 'react';
import { ToastProvider } from './components/Toast';
import { ClientProvider } from './context/ClientContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './pages/Login';
import MobileApp from './mobile/MobileApp';
import StudioApp from './studio/StudioApp';
import { useShellMode } from './shared/useShellMode';
import './studio/theme.css';

/* The desktop web UI is the studio under /studio. On a phone-sized screen the
 * other paths are the mobile app (WP25), built on the studio's data and words,
 * whose paths are the studio's without /studio. */
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
      <div className="studio-root flex min-h-dvh items-center justify-center bg-[var(--studio-bg)]">
        <div role="status" aria-label="読み込んでいます" className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--studio-accent-soft)] border-t-[var(--studio-accent)]" />
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
