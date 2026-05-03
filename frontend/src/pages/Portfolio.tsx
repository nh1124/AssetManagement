import TheLab from './TheLab';

interface PortfolioProps {
    onNavigate?: (page: string) => void;
}

export default function Portfolio({ onNavigate }: PortfolioProps) {
    return <TheLab mode="portfolio" onNavigate={onNavigate} />;
}
