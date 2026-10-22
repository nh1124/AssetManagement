import { Link } from 'react-router-dom';
import { primaryClass } from '../db/forms';
import { tr } from '../../i18n';

export default function NoLifeEvents({ noScenarios = false }: { noScenarios?: boolean }) {
    return <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="font-semibold">{noScenarios ? tr('シナリオがまだありません', 'No scenarios yet') : tr('ライフイベントがまだありません', 'No life events yet')}</h2>
        <div className="flex justify-end"><Link to="/goals/scenarios" className={primaryClass}>{noScenarios ? tr('シナリオを作成する', 'Create a scenario') : tr('ライフイベントを設定する', 'Set up life events')}</Link></div>
    </div>;
}
