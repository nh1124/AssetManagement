import { Link } from 'react-router-dom';
import { primaryClass } from '../db/forms';

export default function NoLifeEvents({ noScenarios = false }: { noScenarios?: boolean }) {
    return <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="font-semibold">{noScenarios ? 'シナリオがまだありません' : 'ライフイベントがまだありません'}</h2>
        <div className="flex justify-end"><Link to={noScenarios ? "/goals/graph" : "/goals/events"} className={primaryClass}>{noScenarios ? 'シナリオを作成する' : 'ライフイベントを設定する'}</Link></div>
    </div>;
}
