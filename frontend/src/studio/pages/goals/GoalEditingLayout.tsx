import { Link, Outlet, useLocation } from 'react-router-dom';
import { useLanguage } from '../../i18n';
import { buttonClass, primaryClass } from '../db/forms';

const steps = [
    { path: '/goals/events', label: 'tab.lifeEvents' },
    { path: '/goals/graph', label: 'tab.graph' },
    { path: '/goals/simulation', label: 'tab.simulation' },
] as const;

export default function GoalEditingLayout() {
    const { pathname } = useLocation();
    const { t } = useLanguage();
    const current = steps.findIndex((step) => pathname === step.path || pathname.startsWith(`${step.path}/`));
    const next = steps[current + 1];
    return <div className="space-y-5">
        <Link to="/goals" className={`inline-block ${buttonClass}`}>ゴールに戻る</Link>
        <nav aria-label="ゴールの編集手順">
            <ol className="grid gap-2 sm:grid-cols-3">
                {steps.map((step, index) => <li key={step.path}>
                    <Link to={step.path} aria-current={index === current ? 'step' : undefined}
                        className={`flex items-center gap-2 rounded-lg border p-3 text-sm ${index === current ? 'border-[var(--studio-accent)] bg-[var(--studio-accent-soft)] font-semibold text-[var(--studio-accent)]' : 'border-[var(--studio-border)] text-[var(--studio-text-muted)] hover:bg-[var(--studio-surface)]'}`}>
                        <span>{index + 1}</span>{t(step.label)}
                    </Link>
                </li>)}
            </ol>
        </nav>
        <Outlet />
        {next && <div className="flex justify-end"><Link to={next.path} className={primaryClass}>次へ：{t(next.label)}</Link></div>}
    </div>;
}
