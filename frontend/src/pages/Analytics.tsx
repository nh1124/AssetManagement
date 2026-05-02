import TheLab from './TheLab';

interface AnalyticsProps {
    onNavigate?: (page: string) => void;
}

export default function Analytics({ onNavigate }: AnalyticsProps) {
    return <TheLab onNavigate={onNavigate} />;
}
