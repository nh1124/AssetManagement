import { useState } from 'react';
import './index.css';
import Layout from './components/Layout';
import Home from './pages/Home';
import TheLab from './pages/TheLab';
import Strategy from './pages/Strategy';

function App() {
  const [currentPage, setCurrentPage] = useState('home');

  const renderPage = () => {
    switch (currentPage) {
      case 'home':
        return <Home />;
      case 'lab':
        return <TheLab />;
      case 'strategy':
        return <Strategy />;
      default:
        return <Home />;
    }
  };

  return (
    <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
      {renderPage()}
    </Layout>
  );
}

export default App;
