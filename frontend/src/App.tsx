import { useState } from 'react';
import './index.css';
import Layout from './components/Layout';
import QuickInputDrawer from './components/QuickInputDrawer';
import { ToastProvider } from './components/Toast';
import RecordPage from './pages/Record';
import TheLab from './pages/TheLab';
import Strategy from './pages/Strategy';
import Inventory from './pages/Inventory';
import SettingsPage from './pages/Settings';

function App() {
  const [currentPage, setCurrentPage] = useState('record');
  const [isQuickInputOpen, setIsQuickInputOpen] = useState(false);

  const renderPage = () => {
    switch (currentPage) {
      case 'record':
        return <RecordPage />;
      case 'analytics':
        return <TheLab />;
      case 'strategy':
        return <Strategy />;
      case 'inventory':
        return <Inventory />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <RecordPage />;
    }
  };

  return (
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
  );
}

export default App;
