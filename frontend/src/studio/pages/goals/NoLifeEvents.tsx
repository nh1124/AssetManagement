import { Link } from 'react-router-dom';
import { primaryClass } from '../db/forms';

export default function NoLifeEvents() {
    return <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="font-semibold">ライフイベントがまだありません</h2>
        <div className="flex justify-end"><Link to="/goals/events" className={primaryClass}>ライフイベントを設定する</Link></div>
    </div>;
}
