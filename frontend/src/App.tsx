import { useState } from 'react';
import './index.css';
import Layout from './components/Layout';
import RecordDrawer from './components/RecordDrawer';
import TheLab from './pages/TheLab';
import Strategy from './pages/Strategy';
import Products from './pages/Products';
import SettingsPage from './pages/Settings';

function App() {
  const [currentPage, setCurrentPage] = useState('strategy'); // Strategy is the heart
  const [isRecordOpen, setIsRecordOpen] = useState(false);

  const renderPage = () => {
    switch (currentPage) {
      case 'analytics':
        return <TheLab />;
      case 'strategy':
        return <Strategy />;
      case 'products':
        return <Products />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <Strategy />;
    }
  };

  return (
    <>
      <Layout
        currentPage={currentPage}
        onNavigate={setCurrentPage}
        onOpenRecord={() => setIsRecordOpen(true)}
      >
        {renderPage()}
      </Layout>
      <RecordDrawer
        isOpen={isRecordOpen}
        onClose={() => setIsRecordOpen(false)}
      />
    </>
  );
}

export default App;
