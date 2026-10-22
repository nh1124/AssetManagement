import { useCallback, useId, useState, type FormEvent } from 'react';
import { getSimulationConfig, saveSimulationConfig, type SimulationConfig } from '../../api/lifeScenarios';
import { Help } from '../components/Help';
import { useResource } from '../useResource';
import { Feedback, Field } from './db/Database';
import { inputClass, primaryClass, useMutation } from './db/forms';
import { tr } from '../i18n';

function ConfigForm({ config, disabled, onSave }: { config: SimulationConfig; disabled: boolean; onSave: (next: Omit<SimulationConfig, 'id'>) => void }) {
    const form = useId();
    const [volatility, setVolatility] = useState(String(config.volatility));
    const [tax, setTax] = useState(String(config.tax_rate));
    const [error, setError] = useState('');
    const changed = volatility !== String(config.volatility) || tax !== String(config.tax_rate);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || !changed) return;
        const values = [Number(volatility), Number(tax)];
        if (!volatility.trim() || !tax.trim() || values.some((value) => !Number.isFinite(value) || value < 0) || values[1] > 100) {
            setError(tr('変動率は0以上、税率は0〜100の数値で入力してください。', 'Enter a volatility of 0 or more and a tax rate from 0 to 100.'));
            return;
        }
        setError('');
        // The backend replaces the whole config: keep the fields this form does not show.
        onSave({ horizon_years: config.horizon_years, annual_return: config.annual_return, is_nisa: config.is_nisa, inflation_rate: config.inflation_rate,
            volatility: values[0], tax_rate: values[1] });
    };
    return <form id={form} onSubmit={submit} className="space-y-3">
        <Feedback error={error} />
        <fieldset disabled={disabled} className="grid items-end gap-4 sm:grid-cols-3">
            <Field label={tr('変動率（%）', 'Volatility (%)')} help={tr('年利が1%を超える口座の、年ごとのぶれの大きさ（標準偏差）です。', 'How much yearly returns swing (standard deviation) for accounts earning more than 1% a year.')}><input inputMode="decimal" required value={volatility} onChange={(event) => setVolatility(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('税率（%）', 'Tax rate (%)')} help={tr('運用益にかかる税の割合です。プラスの年利から差し引きます。', 'The tax on investment gains, taken off positive returns.')}><input inputMode="decimal" required value={tax} onChange={(event) => setTax(event.target.value)} className={inputClass} /></Field>
            <div><button type="submit" disabled={disabled || !changed} className={primaryClass}>{tr('保存', 'Save')}</button></div>
        </fieldset>
    </form>;
}

/** 変動率 and 税率: simulation settings common to every scenario (§8-11); each scenario keeps its own 前提. */
export default function SimulationSettings({ disabled, sectionClass }: { disabled: boolean; sectionClass: string }) {
    const load = useCallback(() => getSimulationConfig(), []);
    const resource = useResource(load);
    const mutation = useMutation();
    const config = resource.data;
    const locked = disabled || mutation.busy || resource.loading || Boolean(resource.error);
    return <details className={sectionClass}>
        <summary className="cursor-pointer text-sm font-semibold"><span className="inline-flex items-center gap-1.5">{tr('シミュレーション', 'Simulation')}<Help label={tr('シミュレーション', 'Simulation')} text={tr('すべてのシナリオに共通の設定です。期間・既定の年利・インフレはシナリオごとの前提（と期間ごとの前提）で決めます。', 'Settings shared by every scenario. The horizon, default return and inflation come from each scenario’s assumptions (and its assumption periods).')} /></span></summary>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} message={mutation.message} />
        {config && <ConfigForm key={`${config.volatility}:${config.tax_rate}`} config={config} disabled={locked}
            onSave={(next) => void mutation.run(() => saveSimulationConfig(next), tr('シミュレーションの設定を保存しました。', 'Simulation settings saved.'), resource.reload)} />}
    </details>;
}
