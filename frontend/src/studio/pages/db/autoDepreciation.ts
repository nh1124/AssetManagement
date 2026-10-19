import { patchProduct } from '../../../api';
import type { AutomaticDepreciationRecording } from '../../../types';
import type { useConfirm } from '../../components/useConfirm';
import type { useMutation } from './forms';

/** The product API owns this switch. */
export async function toggleAutoDepreciation(
    confirm: ReturnType<typeof useConfirm>, mutation: ReturnType<typeof useMutation>,
    row: Pick<AutomaticDepreciationRecording, 'product_id' | 'name' | 'auto_depreciation'>,
    onDone: () => void,
) {
    const enabling = !row.auto_depreciation;
    const body = enabling
        ? `「${row.name}」の減価を、毎期の末日に自動で記帳しますか？`
        : `「${row.name}」の減価の自動記帳を止めますか？\n記帳済みの取引はそのまま残ります。`;
    if (!(await confirm(body, enabling ? '自動で記帳する' : '止める'))) return;
    void mutation.run(
        () => patchProduct(row.product_id, { auto_depreciation: enabling }),
        enabling ? `「${row.name}」の減価を自動で記帳します。` : `「${row.name}」の減価の自動記帳を止めました。`,
        onDone,
    );
}
