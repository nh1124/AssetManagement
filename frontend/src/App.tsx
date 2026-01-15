import { useState } from 'react';
import './index.css';
import Layout from './components/Layout';
import QuickInputDrawer from './components/QuickInputDrawer';
import { ToastProvider } from './components/Toast';
import { ClientProvider } from './context/ClientContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import Journal from './pages/Journal';
import TheLab from './pages/TheLab';
import Strategy from './pages/Strategy';
import Registry from './pages/Registry';
import SettingsPage from './pages/Settings';
import LoginPage from './pages/Login';

function AppContent() {
  const { isAuthenticated, isLoading } = useAuth();
  const [currentPage, setCurrentPage] = useState('journal');
  const [isQuickInputOpen, setIsQuickInputOpen] = useState(false);

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

  const renderPage = () => {
    switch (currentPage) {
      case 'journal':
        return <Journal />;
      case 'analytics':
        return <TheLab />;
      case 'strategy':
        return <Strategy />;
      case 'registry':
        return <Registry />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <Journal />;
    }
  };

  return (
    <ClientProvider>
      <ToastProvider>
        <Layout
          currentPage={currentPage}
          onNavigate={setCurrentPage}
          onOpenQuickInput={() => setIsQuickInputOpen(true)}
        >
          {renderPage()}
        </Layout>
        <QuickInputDrawer
          isOpen={isQuickInputOpen}
          onClose={() => setIsQuickInputOpen(false)}
        />
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
