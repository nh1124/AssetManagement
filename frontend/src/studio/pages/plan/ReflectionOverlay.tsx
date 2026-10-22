import { useCallback, useState } from 'react';
import {
    getReflection, previewReflection, runReflection, saveReflectionSettings,
    type ReflectionChange, type ReflectionPreview, type ReflectionRun, type ReflectionSettings, type ReflectionTrigger,
} from '../../../api/planReflection';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { formatDateTime, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Help, OptionGroup } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';
import { tr, labels } from '../../i18n';

const TRIGGERS = labels<ReflectionTrigger>({ month: ['月の初め', 'Start of month'], change: ['変更', 'Change'], settings: ['設定の保存', 'Settings saved'], manual: ['今すぐ反映', 'Reflect now'] });
const help = () => tr(
    '計画のうち、ゴール（積立設定・ライフイベントの取り置き）と、物品にひもづく取り置きの行をこの設定で作ります。'
    + '自動反映がオンなら、月の初めと、積立設定・ライフイベント・取り置き・物品・自動取引・予算のレコードを変えたときに、今月から 12 か月分を作り直します。'
    + '過去の月とユーザーのレコードは変えません。',
    'These settings write the plan’s goal rows (contribution settings and life-event earmarks) and the earmark rows linked to items. '
    + 'With automatic reflection on, the next 12 months are rebuilt at the start of each month and whenever contribution settings, life events, earmarks, items, automatic transactions or budget records change. '
    + 'Past months and your own records are never changed.',
);

function rowLabel(change: ReflectionChange): string {
    const account = change.account_name ?? tr('口座なし', 'no account');
    if (change.kind === 'drawdown') return tr(`口座「${account}」からの取り崩し`, `Drawdown from “${account}”`);
    if (change.kind === 'account') return tr(`口座「${account}」への積立`, `Contribution to “${account}”`);
    if (change.kind === 'transfer') return tr(`口座「${change.source_account_name ?? '—'}」から「${account}」への振替`, `Transfer from “${change.source_account_name ?? '—'}” to “${account}”`);
    const name = change.capsule_name ?? tr('取り置き', 'Earmark');
    return change.new_capsule ? tr(`新しい取り置き「${name}」（${account}）`, `New earmark “${name}” (${account})`) : tr(`取り置き「${name}」（${account}）`, `Earmark “${name}” (${account})`);
}

function Changes({ changes, currency }: { changes: ReflectionChange[]; currency: string }) {
    if (!changes.length) return <p className="text-sm text-[var(--studio-text-muted)]">{tr('計画は設定どおりです。変える行はありません。', 'The plan matches the settings. No rows change.')}</p>;
    return <DataTable columns={[tr('月', 'Month'), tr('計画の行', 'Plan row'), tr('現在', 'Now'), tr('変更後', 'After')]}>
        {changes.map((change, index) => <tr key={`${change.period}:${change.kind}:${index}`}>
            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.period}</td>
            <th scope="row" className="px-5 py-3 font-normal">{rowLabel(change)}</th>
            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(change.current, currency)}</td>
            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.retire ? tr('削除', 'Removed') : formatCurrency(change.new, currency)}</td>
        </tr>)}
    </DataTable>;
}

function History({ runs, currency }: { runs: ReflectionRun[]; currency: string }) {
    const timezone = useTimezone();
    if (!runs.length) return <p className="text-sm text-[var(--studio-text-muted)]">{tr('まだ反映していません。', 'Nothing reflected yet.')}</p>;
    return <ul className="space-y-2">{runs.map((run) => <li key={run.id}><details className="rounded-md border border-[var(--studio-border)] p-3 text-sm">
        <summary className="cursor-pointer">
            <span className="tabular-nums">{run.applied_at ? formatDateTime(`${run.applied_at}Z`, timezone) : '—'}</span>
            <span className="ml-3 text-[var(--studio-text-muted)]">{tr(`${TRIGGERS[run.trigger]}・${run.start_period}〜${run.end_period}・${run.changes}件`, `${TRIGGERS[run.trigger]} · ${run.start_period} to ${run.end_period} · ${run.changes} rows`)}</span>
        </summary>
        <div className="mt-3 space-y-2">
            {run.warnings.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--studio-warning)]">{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
            <Changes changes={run.rows} currency={run.currency ?? currency} />
        </div>
    </details></li>)}</ul>;
}

function SettingsForm({ saved, busy, onSave, onPreview }: {
    saved: ReflectionSettings; busy: boolean;
    onSave: (next: ReflectionSettings) => void; onPreview: (next: ReflectionSettings) => void;
}) {
    const [draft, setDraft] = useState(saved);
    const changed = JSON.stringify(draft) !== JSON.stringify(saved);
    const goal = <K extends keyof ReflectionSettings['goal']>(key: K, value: ReflectionSettings['goal'][K]) => setDraft({ ...draft, goal: { ...draft.goal, [key]: value } });
    const products = <K extends keyof ReflectionSettings['products']>(key: K, value: ReflectionSettings['products'][K]) => setDraft({ ...draft, products: { ...draft.products, [key]: value } });
    return <fieldset disabled={busy} className="space-y-5">
        <label className="flex items-start gap-3 rounded-md border border-[var(--studio-border)] p-3 text-sm has-checked:border-[var(--studio-accent)] has-checked:bg-[var(--studio-accent-soft)]">
            <input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} className="mt-1 accent-[var(--studio-accent)]" />
            <span><span className="font-medium">{tr('自動反映', 'Automatic reflection')}</span><span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{tr('月の初めと、計画のもとになる設定を変えたときに、今月から 12 か月分を自動で作り直します。', 'Rebuilds the next 12 months automatically at the start of each month and when the settings behind the plan change.')}</span></span>
        </label>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">{tr('ゴール', 'Goals')}</h3>
            <OptionGroup label={tr('取り置きの基準', 'Earmark basis')} value={draft.goal.base} onChange={(value) => goal('base', value)} options={[
                { value: 'remaining', label: tr('残り期間に合わせる', 'Fit the time left'), description: tr('目標から確保済みの額を引いた残りを、最初の取り崩しの月までの月数で割ります。遅れはその都度、残りの月に均等に上乗せされます。', 'Divides what is left of the target, after what is already set aside, by the months until the first drawdown. A shortfall is spread over the remaining months as it happens.') },
                { value: 'goal_setting', label: tr('積立設定から決まる額', 'Amount from the contribution settings'), description: tr('取り置きを作った月から最初の取り崩しの月までで目標を割った月額を固定で使います。予定より多く確保していれば差し引き、遅れていれば下の「遅れの取り返し」に従います。', 'Uses a fixed monthly amount: the target divided over the months from the earmark’s creation to the first drawdown. Anything set aside ahead of schedule is taken off; a shortfall follows “Catching up” below.') },
            ]} />
            <OptionGroup label={tr('確保済みの額の引き方', 'Using what is set aside')} value={draft.goal.held} onChange={(value) => goal('held', value)} options={[
                { value: 'even', label: tr('均一に引く', 'Spread evenly'), description: tr('確保済みの額（基準が「積立設定から決まる額」のときは予定を超えた分）を、残りの月に同じ額ずつ割り振って引きます。', 'Takes what is already set aside (with “Amount from the contribution settings”, only what is ahead of schedule) off the remaining months in equal parts.') },
                { value: 'recent', label: tr('直近の月から引く', 'Nearest months first'), description: tr('使い切るまで、今月に近い月から引きます。', 'Takes it off the months nearest to now until it is used up.') },
            ]} />
            <OptionGroup label={tr('遅れの取り返し', 'Catching up')} help={tr('積立の遅れは、設定を最初に保存した月からの、積立設定の月額（振替・取り崩しを含む）と口座に実際に入った額の差です。取り置きの遅れは「積立設定から決まる額」のときの予定との差です。', 'A contribution shortfall is the gap, since the month the settings were first saved, between the monthly amounts in the contribution settings (transfers and drawdowns included) and what actually reached the account. An earmark shortfall is the gap to the schedule under “Amount from the contribution settings”.')} value={draft.goal.catch_up} onChange={(value) => goal('catch_up', value)} options={[
                { value: 'even', label: tr('残りの月に均等', 'Evenly over the remaining months'), description: tr('遅れた額を、取り置きは最初の取り崩しの月まで、積立は 12 か月に均等に上乗せします。', 'Adds the shortfall evenly: for earmarks until the first drawdown, for contributions over 12 months.') },
                { value: 'recent', label: tr('今月に上乗せ', 'All this month'), description: tr('遅れた額をすべて今月の行に上乗せします。', 'Adds the whole shortfall to this month’s rows.') },
                { value: 'none', label: tr('取り返さない', 'Do not catch up'), description: tr('上乗せしません。不足はシミュレーションの確率に表れます。', 'Adds nothing. The shortfall shows in the simulation’s probabilities.') },
            ]} />
        </section>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">{tr('物品の取り置き', 'Item earmarks')}</h3>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.products.enabled} onChange={(event) => products('enabled', event.target.checked)} className="accent-[var(--studio-accent)]" />{tr('物品にひもづく取り置きの行を作る', 'Write earmark rows for items')}</label>
            {draft.products.enabled && <>
                <OptionGroup label={tr('基準', 'Basis')} value={draft.products.base} onChange={(value) => products('base', value)} options={[
                    { value: 'remaining', label: tr('残り期間に合わせる', 'Fit the time left'), description: tr('今月から買い替えの月までに目標に届く月額です（消耗品は月あたりの費用）。', 'The monthly amount that reaches the target by the replacement month (for consumables, the monthly cost).') },
                    { value: 'saved', label: tr('取り置きの月額', 'Earmark’s monthly amount'), description: tr('取り置きの月額（物品の合計）をそのまま使います。', 'Uses the earmark’s monthly amount (the items’ total) as it is.') },
                ]} />
                <OptionGroup label={tr('確保済みの額の引き方', 'Using what is set aside')} value={draft.products.held} onChange={(value) => products('held', value)} options={[
                    { value: 'even', label: tr('均一に引く', 'Spread evenly'), description: tr('確保済みの額を買い替えの月までの月数で割り、毎月同じ額を引きます。', 'Divides what is set aside by the months until replacement and takes the same amount off each month.') },
                    { value: 'recent', label: tr('直近の月から引く', 'Nearest months first'), description: tr('使い切るまで、今月に近い月から引きます。', 'Takes it off the months nearest to now until it is used up.') },
                ]} />
            </>}
        </section>
        <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => onPreview(draft)} className={buttonClass}>{tr('変わる行を確認', 'Preview changes')}</button>
            <button type="button" disabled={!changed} onClick={() => onSave(draft)} className={primaryClass}>{tr('設定を保存', 'Save settings')}</button>
            {changed && <span className="self-center text-xs text-[var(--studio-text-muted)]">{tr('保存していない変更があります。', 'You have unsaved changes.')}</span>}
        </div>
    </fieldset>;
}

/** ⚙ 計画への反映: how the goal and the product earmarks are written into the plan, what a run would change, and the latest runs. */
export default function ReflectionOverlay({ clientName, currency, intro, onClose }: {
    clientName?: string; currency: string; intro?: string; onClose: (changed: boolean) => void;
}) {
    const confirm = useConfirm();
    const load = useCallback(() => getReflection(), []);
    const state = useResource(load);
    const mutation = useMutation();
    const [preview, setPreview] = useState<ReflectionPreview | null>(null);
    const [changed, setChanged] = useState(false);
    const data = state.data;
    const busy = mutation.busy || state.loading || !clientName;
    const done = () => { setChanged(true); setPreview(null); state.reload(); };
    const save = (next: ReflectionSettings) => {
        void mutation.run(() => saveReflectionSettings({ enabled: next.enabled, goal: next.goal, products: next.products }),
            next.enabled ? tr('設定を保存し、計画を作り直しました。', 'Settings saved and the plan rebuilt.') : tr('設定を保存しました。', 'Settings saved.'), done);
    };
    const check = (next: ReflectionSettings) => {
        let loaded: ReflectionPreview | null = null;
        void mutation.run(async () => { loaded = await previewReflection({ goal: next.goal, products: next.products }); }, '', () => setPreview(loaded));
    };
    const run = async () => {
        if (busy || !data) return;
        if (!(await confirm(tr(`「${clientName}」の計画に、保存した設定で ${data.periods[0]}〜${data.periods.at(-1)} を反映しますか？\n過去の月とユーザーのレコードは変わりません。`, `Reflect ${data.periods[0]} to ${data.periods.at(-1)} into the plan of “${clientName}” with the saved settings?\nPast months and your own records do not change.`), tr('反映する', 'Reflect')))) return;
        void mutation.run(() => runReflection(), tr('計画に反映しました。', 'Reflected into the plan.'), done);
    };
    return <Overlay title={tr('計画への反映', 'Plan reflection')} help={help()} busy={mutation.busy} onClose={() => onClose(changed)} footer={<>
        <button type="button" disabled={busy || !data} onClick={() => void run()} className={primaryClass}>{tr('今すぐ反映', 'Reflect now')}</button>
        <button type="button" disabled={mutation.busy} onClick={() => onClose(changed)} className={buttonClass}>{tr('閉じる', 'Close')}</button>
    </>}>
        <div className="space-y-6">
            {intro && <p className="text-sm">{intro}</p>}
            <Feedback loading={state.loading && !data} error={state.error || mutation.error} message={mutation.message} />
            {data && <>
                <p className="text-xs text-[var(--studio-text-muted)]">
                    {data.settings.enabled ? tr('自動反映：オン', 'Automatic reflection: on') : tr('自動反映：オフ（「今すぐ反映」で作ります）', 'Automatic reflection: off (use “Reflect now”)')}{tr(`・対象 ${data.periods[0]}〜${data.periods.at(-1)}`, ` · ${data.periods[0]} to ${data.periods.at(-1)}`)}
                </p>
                <SettingsForm key={JSON.stringify(data.settings)} saved={data.settings} busy={busy} onSave={save} onPreview={check} />
                {preview && <section className="space-y-2">
                    <h3 className="text-sm font-semibold">{tr(`この設定で変わる行（${preview.changes.length}件）`, `Rows these settings change (${preview.changes.length})`)}</h3>
                    {preview.warnings.length > 0 && <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-[var(--studio-warning)]">{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                    <Changes changes={preview.changes} currency={preview.currency ?? currency} />
                </section>}
                <section className="space-y-2">
                    <h3 className="flex items-center gap-1.5 text-sm font-semibold">{tr('反映の履歴', 'Reflection history')}<Help label={tr('反映の履歴', 'Reflection history')} text={tr('直近 10 回の反映です。変えた行を開いて確認できます。', 'The last 10 runs. Open one to see the rows it changed.')} /></h3>
                    <History runs={data.history} currency={currency} />
                </section>
            </>}
        </div>
    </Overlay>;
}
