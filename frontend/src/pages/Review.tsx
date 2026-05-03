import TheLab from './TheLab';

interface ReviewProps {
    onNavigate?: (page: string) => void;
}

export default function Review({ onNavigate }: ReviewProps) {
    return <TheLab mode="period" onNavigate={onNavigate} />;
}
