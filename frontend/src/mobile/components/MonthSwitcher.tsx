import { ChevronLeft, ChevronRight } from 'lucide-react';
import { addMonths, monthLabel } from '../months';
import { focusRing } from './ui';

/** ‹ 2026年10月 › with a way back to this month. */
export default function MonthSwitcher({ period, current, onChange }: { period: string; current: string; onChange: (period: string) => void }) {
    const button = `flex h-11 w-11 items-center justify-center rounded-full text-[var(--studio-text-muted)] active:bg-[var(--studio-accent-soft)] ${focusRing}`;
    return <div className="flex items-center justify-between">
        <button type="button" onClick={() => onChange(addMonths(period, -1))} aria-label="前の月" className={button}><ChevronLeft size={20} aria-hidden /></button>
        <div className="flex items-center gap-2">
            <span className="text-base font-semibold tabular-nums" aria-live="polite">{monthLabel(period)}</span>
            {period !== current && <button type="button" onClick={() => onChange(current)} className={`min-h-9 rounded-full bg-[var(--studio-accent-soft)] px-3 text-xs font-medium text-[var(--studio-accent)] ${focusRing}`}>今月</button>}
        </div>
        <button type="button" onClick={() => onChange(addMonths(period, 1))} aria-label="次の月" className={button}><ChevronRight size={20} aria-hidden /></button>
    </div>;
}
