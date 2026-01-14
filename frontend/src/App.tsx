import { useState } from 'react';
import './index.css';
import Layout from './components/Layout';
import TheLab from './pages/TheLab';
import Strategy from './pages/Strategy';
import Status from './pages/Status';
import Products from './pages/Products';

function App() {
  const [currentPage, setCurrentPage] = useState('analytics');

  const renderPage = () => {
    switch (currentPage) {
      case 'analytics':
        return <TheLab />;
      case 'strategy':
        return <Strategy />;
      case 'status':
        return <Status />;
      case 'products':
        return <Products />;
      default:
        return <TheLab />;
    }
  };

  return (
    <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
      {renderPage()}
    </Layout>
  );
}

export default App;
