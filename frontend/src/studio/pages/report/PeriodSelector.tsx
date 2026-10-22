import { Field } from '../db/Database';
import { inputClass } from '../db/forms';
import { tr } from '../../i18n';

export default function PeriodSelector({ months, onChange, disabled = false }: {
    months: number; onChange: (months: number) => void; disabled?: boolean;
}) {
    return <div className="studio-period-selector w-40 shrink-0"><Field label={tr('表示期間', 'Period')}><select value={months} disabled={disabled} onChange={(event) => onChange(Number(event.target.value))} className={inputClass}>
        {[1, 12, 36, 60].map((value) => <option key={value} value={value}>{tr(`${value}か月`, value === 1 ? '1 month' : `${value} months`)}</option>)}
    </select></Field></div>;
}
