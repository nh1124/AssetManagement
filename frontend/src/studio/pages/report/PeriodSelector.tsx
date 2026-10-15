import { Field } from '../db/Database';
import { inputClass } from '../db/forms';

export default function PeriodSelector({ months, onChange, disabled = false }: {
    months: number; onChange: (months: number) => void; disabled?: boolean;
}) {
    return <div className="studio-period-selector"><Field label="表示期間"><select value={months} disabled={disabled} onChange={(event) => onChange(Number(event.target.value))} className={inputClass}>
        {[1, 12, 36, 60].map((value) => <option key={value} value={value}>{value}か月</option>)}
    </select></Field></div>;
}
