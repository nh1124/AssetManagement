import { useState, type ReactNode } from 'react';
import { goalPreview, makeGoal, type GoalChangePreview, type GoalEarmarkChoice, type LifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';
import ReflectionOverlay from '../plan/ReflectionOverlay';

const CHOICES: Array<{ value: GoalEarmarkChoice; label: string; description: string }> = [
    { value: 'carry', label: '同じライフイベントへ引き継ぐ', description: '複製したシナリオどうしで同じイベントの取り置きを、確保額ごと新しいゴールのイベントに付け替えます。対応するイベントが無い取り置きはそのまま残ります。' },
    { value: 'keep', label: 'そのまま', description: '取り置きは何も変えません。前のゴールの取り置きは、ゴールの取り置きとしては数えなくなります。' },
    { value: 'replace', label: '取り置きを削除して作り直す', description: '前のゴールの取り置きを削除し（確保額は口座に戻ります）、今月以降の前のゴールの計画行を外します。新しいゴールのイベントに取り置きを作ります。' },
];

/** Choose what happens to the old goal's earmarks, then the scenario becomes the goal (R11).
 *
 * The choice and every change it makes happen in the backend; this shows what each
 * choice would touch and offers making the plan afterwards.
 */
export function useMakeScenarioGoal(onSuccess: () => void): ReturnType<typeof useMutation> & { chooseGoal: (scenario: Pick<LifeScenario, 'id' | 'name'>) => void; dialog: ReactNode } {
    const mutation = useMutation();
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [preview, setPreview] = useState<GoalChangePreview | null>(null);
    const [choice, setChoice] = useState<GoalEarmarkChoice>('keep');
    const [planning, setPlanning] = useState(false);
    const chooseGoal = (scenario: Pick<LifeScenario, 'id' | 'name'>) => {
        let loaded: GoalChangePreview | null = null;
        void mutation.run(async () => { loaded = await goalPreview(scenario.id); }, '', () => {
            const found: GoalChangePreview | null = loaded;
            if (!found) return;
            setChoice(found.capsules.some((row) => row.carry_to) ? 'carry' : 'keep');
            setPreview(found);
        });
    };
    const confirm = () => {
        if (!preview) return;
        void mutation.run(() => makeGoal(preview.scenario.id, choice), 'ゴールにしました。', () => { setPreview(null); setPlanning(true); });
    };
    const options = preview && preview.capsules.length ? CHOICES : CHOICES.filter((option) => option.value === 'keep');
    const dialog = preview ? <Overlay title={`「${preview.scenario.name}」をゴールにする`} busy={mutation.busy} onClose={() => setPreview(null)} footer={<>
        <button type="button" disabled={mutation.busy} onClick={confirm} className={primaryClass}>{mutation.busy ? '処理中…' : 'ゴールにする'}</button>
        <button type="button" disabled={mutation.busy} onClick={() => setPreview(null)} className={buttonClass}>キャンセル</button>
    </>}>
        <div className="space-y-4">
            <p className="text-sm">{preview.current_goal ? `いまのゴールは「${preview.current_goal.name}」です。` : 'いまはゴールがありません。'}自動反映がオンなら計画もこのゴールに合わせて作り直します。オフなら計画の ⚙ から「今すぐ反映」で作ります。</p>
            <Feedback error={mutation.error} />
            {preview.capsules.length > 0 && <>
                <h3 className="text-sm font-semibold">前のゴールの取り置き</h3>
                <DataTable columns={['取り置き', 'ライフイベント', '確保額', '引き継ぎ先']}>
                    {preview.capsules.map((row) => <tr key={row.capsule_id}>
                        <th scope="row" className="px-5 py-3 font-medium">{row.capsule_name}</th>
                        <td className="px-5 py-3">{row.event_name}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.claim, currency)}</td>
                        <td className="px-5 py-3">{row.carry_to ?? <span className="text-[var(--studio-text-muted)]">対応なし</span>}</td>
                    </tr>)}
                </DataTable>
            </>}
            <fieldset className="space-y-2">
                <legend className="mb-2 text-sm font-semibold">取り置きの扱い</legend>
                {options.map((option) => <label key={option.value} className="flex cursor-pointer gap-3 rounded-md border border-[var(--studio-border)] p-3 text-sm has-checked:border-[var(--studio-accent)] has-checked:bg-[var(--studio-accent-soft)]">
                    <input type="radio" name="goal-earmarks" value={option.value} checked={choice === option.value} onChange={() => setChoice(option.value)} className="mt-1 accent-[var(--studio-accent)]" />
                    <span><span className="font-medium">{option.label}</span><span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{option.description}</span></span>
                </label>)}
            </fieldset>
            {choice === 'replace' && preview.create.length > 0 && <p className="text-xs text-[var(--studio-text-muted)]">作る取り置き：{preview.create.map((row) => `「${row.name}」（${row.account_name ?? '口座なし'}）`).join('、')}</p>}
        </div>
    </Overlay> : planning ? <ReflectionOverlay clientName={currentClient && currentClient.id === clientId ? currentClient.name : undefined}
        currency={currency}
        intro="ゴールを変更しました。自動反映がオンなら計画はもう作り直しています。オフなら「今すぐ反映」で計画を作ります（後で計画やゴールの画面からもできます）。"
        onClose={() => { setPlanning(false); onSuccess(); }} /> : null;
    return { ...mutation, chooseGoal, dialog };
}
