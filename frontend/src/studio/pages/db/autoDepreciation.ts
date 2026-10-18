import { setAutoDepreciation } from '../../../api';
import type { AutomaticDepreciationRecording } from '../../../types';
import type { useConfirm } from '../../components/useConfirm';
import type { useMutation } from './forms';

/** Switch a product's automatic write-down; shared by the definitions list and the fixed-asset screen. */
export async function toggleAutoDepreciation(
    confirm: ReturnType<typeof useConfirm>, mutation: ReturnType<typeof useMutation>,
    row: Pick<AutomaticDepreciationRecording, 'product_id' | 'name' | 'auto_depreciation' | 'pending_periods'>,
    onDone: () => void,
) {
    const enabling = !row.auto_depreciation;
    const body = enabling
        ? `「${row.name}」の減価を、毎期の末日に自動で記帳しますか？`
          + (row.pending_periods ? `\n終わった期のうち未記帳の${row.pending_periods}期分を今すぐ記帳します（1回 24 期まで、残りは翌日以降）。` : '')
        : `「${row.name}」の減価の自動記帳を止めますか？\n記帳済みの取引はそのまま残ります。`;
    if (!(await confirm(body, enabling ? '自動で記帳する' : '止める'))) return;
    void mutation.run(
        () => setAutoDepreciation(row.product_id, enabling),
        enabling ? `「${row.name}」の減価を自動で記帳します。` : `「${row.name}」の減価の自動記帳を止めました。`,
        onDone,
    );
}
