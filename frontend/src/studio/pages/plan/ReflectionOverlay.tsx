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

const TRIGGERS: Record<ReflectionTrigger, string> = { month: '月の初め', change: '変更', settings: '設定の保存', manual: '今すぐ反映' };
const HELP = '計画のうち、ゴール（積立設定・ライフイベントの取り置き）と、物品にひもづく取り置きの行をこの設定で作ります。'
    + '自動反映がオンなら、月の初めと、積立設定・ライフイベント・取り置き・物品・自動取引・予算のレコードを変えたときに、今月から 12 か月分を作り直します。'
    + '過去の月とユーザーのレコードは変えません。';

function rowLabel(change: ReflectionChange): string {
    const account = change.account_name ?? '口座なし';
    if (change.kind === 'drawdown') return `口座「${account}」からの取り崩し`;
    if (change.kind === 'account') return `口座「${account}」への積立`;
    if (change.kind === 'transfer') return `口座「${change.source_account_name ?? '—'}」から「${account}」への振替`;
    const name = change.capsule_name ?? '取り置き';
    return change.new_capsule ? `新しい取り置き「${name}」（${account}）` : `取り置き「${name}」（${account}）`;
}

function Changes({ changes, currency }: { changes: ReflectionChange[]; currency: string }) {
    if (!changes.length) return <p className="text-sm text-[var(--studio-text-muted)]">計画は設定どおりです。変える行はありません。</p>;
    return <DataTable columns={['月', '計画の行', '現在', '変更後']}>
        {changes.map((change, index) => <tr key={`${change.period}:${change.kind}:${index}`}>
            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.period}</td>
            <th scope="row" className="px-5 py-3 font-normal">{rowLabel(change)}</th>
            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(change.current, currency)}</td>
            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.retire ? '削除' : formatCurrency(change.new, currency)}</td>
        </tr>)}
    </DataTable>;
}

function History({ runs, currency }: { runs: ReflectionRun[]; currency: string }) {
    const timezone = useTimezone();
    if (!runs.length) return <p className="text-sm text-[var(--studio-text-muted)]">まだ反映していません。</p>;
    return <ul className="space-y-2">{runs.map((run) => <li key={run.id}><details className="rounded-md border border-[var(--studio-border)] p-3 text-sm">
        <summary className="cursor-pointer">
            <span className="tabular-nums">{run.applied_at ? formatDateTime(`${run.applied_at}Z`, timezone) : '—'}</span>
            <span className="ml-3 text-[var(--studio-text-muted)]">{TRIGGERS[run.trigger]}・{run.start_period}〜{run.end_period}・{run.changes}件</span>
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
            <span><span className="font-medium">自動反映</span><span className="mt-1 block text-xs text-[var(--studio-text-muted)]">月の初めと、計画のもとになる設定を変えたときに、今月から 12 か月分を自動で作り直します。</span></span>
        </label>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">ゴール</h3>
            <OptionGroup label="取り置きの基準" value={draft.goal.base} onChange={(value) => goal('base', value)} options={[
                { value: 'remaining', label: '残り期間に合わせる', description: '目標から確保済みの額を引いた残りを、最初の取り崩しの月までの月数で割ります。遅れはその都度、残りの月に均等に上乗せされます。' },
                { value: 'goal_setting', label: '積立設定から決まる額', description: '取り置きを作った月から最初の取り崩しの月までで目標を割った月額を固定で使います。予定より多く確保していれば差し引き、遅れていれば下の「遅れの取り返し」に従います。' },
            ]} />
            <OptionGroup label="確保済みの額の引き方" value={draft.goal.held} onChange={(value) => goal('held', value)} options={[
                { value: 'even', label: '均一に引く', description: '確保済みの額（基準が「積立設定から決まる額」のときは予定を超えた分）を、残りの月に同じ額ずつ割り振って引きます。' },
                { value: 'recent', label: '直近の月から引く', description: '使い切るまで、今月に近い月から引きます。' },
            ]} />
            <OptionGroup label="遅れの取り返し" help="積立の遅れは、設定を最初に保存した月からの、積立設定の月額（振替・取り崩しを含む）と口座に実際に入った額の差です。取り置きの遅れは「積立設定から決まる額」のときの予定との差です。" value={draft.goal.catch_up} onChange={(value) => goal('catch_up', value)} options={[
                { value: 'even', label: '残りの月に均等', description: '遅れた額を、取り置きは最初の取り崩しの月まで、積立は 12 か月に均等に上乗せします。' },
                { value: 'recent', label: '今月に上乗せ', description: '遅れた額をすべて今月の行に上乗せします。' },
                { value: 'none', label: '取り返さない', description: '上乗せしません。不足はシミュレーションの確率に表れます。' },
            ]} />
        </section>
        <section className="space-y-3">
            <h3 className="text-sm font-semibold">物品の取り置き</h3>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.products.enabled} onChange={(event) => products('enabled', event.target.checked)} className="accent-[var(--studio-accent)]" />物品にひもづく取り置きの行を作る</label>
            {draft.products.enabled && <>
                <OptionGroup label="基準" value={draft.products.base} onChange={(value) => products('base', value)} options={[
                    { value: 'remaining', label: '残り期間に合わせる', description: '今月から買い替えの月までに目標に届く月額です（消耗品は月あたりの費用）。' },
                    { value: 'saved', label: '取り置きの月額', description: '取り置きの月額（物品の合計）をそのまま使います。' },
                ]} />
                <OptionGroup label="確保済みの額の引き方" value={draft.products.held} onChange={(value) => products('held', value)} options={[
                    { value: 'even', label: '均一に引く', description: '確保済みの額を買い替えの月までの月数で割り、毎月同じ額を引きます。' },
                    { value: 'recent', label: '直近の月から引く', description: '使い切るまで、今月に近い月から引きます。' },
                ]} />
            </>}
        </section>
        <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => onPreview(draft)} className={buttonClass}>変わる行を確認</button>
            <button type="button" disabled={!changed} onClick={() => onSave(draft)} className={primaryClass}>設定を保存</button>
            {changed && <span className="self-center text-xs text-[var(--studio-text-muted)]">保存していない変更があります。</span>}
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
            next.enabled ? '設定を保存し、計画を作り直しました。' : '設定を保存しました。', done);
    };
    const check = (next: ReflectionSettings) => {
        let loaded: ReflectionPreview | null = null;
        void mutation.run(async () => { loaded = await previewReflection({ goal: next.goal, products: next.products }); }, '', () => setPreview(loaded));
    };
    const run = async () => {
        if (busy || !data) return;
        if (!(await confirm(`「${clientName}」の計画に、保存した設定で ${data.periods[0]}〜${data.periods.at(-1)} を反映しますか？\n過去の月とユーザーのレコードは変わりません。`, '反映する'))) return;
        void mutation.run(() => runReflection(), '計画に反映しました。', done);
    };
    return <Overlay title="計画への反映" help={HELP} busy={mutation.busy} onClose={() => onClose(changed)} footer={<>
        <button type="button" disabled={busy || !data} onClick={() => void run()} className={primaryClass}>今すぐ反映</button>
        <button type="button" disabled={mutation.busy} onClick={() => onClose(changed)} className={buttonClass}>閉じる</button>
    </>}>
        <div className="space-y-6">
            {intro && <p className="text-sm">{intro}</p>}
            <Feedback loading={state.loading && !data} error={state.error || mutation.error} message={mutation.message} />
            {data && <>
                <p className="text-xs text-[var(--studio-text-muted)]">
                    {data.settings.enabled ? '自動反映：オン' : '自動反映：オフ（「今すぐ反映」で作ります）'}・対象 {data.periods[0]}〜{data.periods.at(-1)}
                </p>
                <SettingsForm key={JSON.stringify(data.settings)} saved={data.settings} busy={busy} onSave={save} onPreview={check} />
                {preview && <section className="space-y-2">
                    <h3 className="text-sm font-semibold">この設定で変わる行（{preview.changes.length}件）</h3>
                    {preview.warnings.length > 0 && <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-[var(--studio-warning)]">{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                    <Changes changes={preview.changes} currency={preview.currency ?? currency} />
                </section>}
                <section className="space-y-2">
                    <h3 className="flex items-center gap-1.5 text-sm font-semibold">反映の履歴<Help label="反映の履歴" text="直近 10 回の反映です。変えた行を開いて確認できます。" /></h3>
                    <History runs={data.history} currency={currency} />
                </section>
            </>}
        </div>
    </Overlay>;
}
