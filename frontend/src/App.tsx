import { useState } from 'react';
import './index.css';
import Layout from './components/Layout';
import QuickInputDrawer from './components/QuickInputDrawer';
import RecordPage from './pages/Record';
import TheLab from './pages/TheLab';
import Strategy from './pages/Strategy';
import Products from './pages/Products';
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
      case 'products':
        return <Products />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <RecordPage />;
    }
  };

  return (
    <>
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
    </>
  );
}

export default App;
