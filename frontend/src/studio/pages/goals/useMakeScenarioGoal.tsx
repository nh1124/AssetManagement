import { useState, type ReactNode } from 'react';
import { makeGoal, type LifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { useConfirm } from '../../components/useConfirm';
import { useMutation } from '../db/forms';
import GoalPlanDialog from './GoalPlanDialog';

/** Make a scenario the goal, then offer to make the plan from it.
 *
 * Choosing the goal only marks the scenario. 実績管理の設定 belongs to each event,
 * so the new goal's events keep whatever earmarks were linked to them.
 */
export function useMakeScenarioGoal(onSuccess: () => void): ReturnType<typeof useMutation> & { chooseGoal: (scenario: Pick<LifeScenario, 'id' | 'name'>) => void; dialog: ReactNode } {
    const mutation = useMutation();
    const confirm = useConfirm();
    const { currentClient } = useClient();
    const [planning, setPlanning] = useState(false);
    const chooseGoal = (scenario: Pick<LifeScenario, 'id' | 'name'>) => {
        void (async () => {
            if (!(await confirm(`「${currentClient?.name ?? ''}」のゴールを「${scenario.name}」に変更します。計画は変わりません（このあと、ゴールから計画を作成できます）。`, 'ゴールにする'))) return;
            await mutation.run(() => makeGoal(scenario.id), 'ゴールにしました。', () => setPlanning(true));
        })();
    };
    const dialog = planning ? <GoalPlanDialog title="計画も作成しますか？" intro="ゴールを変更しました。計画は前のゴールのままです。作成しない場合は閉じてください（ゴールや計画の画面から後で作成できます）。"
        onClose={() => { setPlanning(false); onSuccess(); }} /> : null;
    return { ...mutation, chooseGoal, dialog };
}
