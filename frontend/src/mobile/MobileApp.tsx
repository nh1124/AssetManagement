import { useState } from 'react';
import MobileShell from './components/MobileShell';
import type { MobilePage } from './components/MobileBottomNav';
import MobileQuickPage from './pages/Quick';
import MobileJournalPage from './pages/Journal';
import MobilePortfolioPage from './pages/Portfolio';
import MobilePlanPage from './pages/Plan';
import MobileReviewPage from './pages/Review';
import MobileMorePage from './pages/More';

export default function MobileApp() {
    const [currentPage, setCurrentPage] = useState<MobilePage>('quick');

    const renderPage = () => {
        switch (currentPage) {
            case 'quick':
                return <MobileQuickPage />;
            case 'journal':
                return <MobileJournalPage />;
            case 'portfolio':
                return <MobilePortfolioPage />;
            case 'plan':
                return <MobilePlanPage />;
            case 'review':
                return <MobileReviewPage />;
            case 'more':
                return <MobileMorePage />;
            default:
                return <MobileQuickPage />;
        }
    };

    return (
        <MobileShell currentPage={currentPage} onNavigate={setCurrentPage}>
            {renderPage()}
        </MobileShell>
    );
}
