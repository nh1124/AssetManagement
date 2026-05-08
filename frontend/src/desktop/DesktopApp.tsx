import { useState } from 'react';
import QuickInputDrawer from '../components/QuickInputDrawer';
import Goal from '../pages/Goal';
import Journal from '../pages/Journal';
import Portfolio from '../pages/Portfolio';
import Registry from '../pages/Registry';
import Review from '../pages/Review';
import SettingsPage from '../pages/Settings';
import Strategy from '../pages/Strategy';
import DesktopLayout from './components/DesktopLayout';

export default function DesktopApp() {
    const [currentPage, setCurrentPage] = useState('journal');
    const [isQuickInputOpen, setIsQuickInputOpen] = useState(false);

    const renderPage = () => {
        switch (currentPage) {
            case 'journal':
                return <Journal />;
            case 'goal':
                return <Goal />;
            case 'portfolio':
                return <Portfolio onNavigate={setCurrentPage} />;
            case 'review':
                return <Review onNavigate={setCurrentPage} />;
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
        <>
            <DesktopLayout
                currentPage={currentPage}
                onNavigate={setCurrentPage}
                onOpenQuickInput={() => setIsQuickInputOpen(true)}
            >
                {renderPage()}
            </DesktopLayout>
            <QuickInputDrawer
                isOpen={isQuickInputOpen}
                onClose={() => setIsQuickInputOpen(false)}
            />
        </>
    );
}
