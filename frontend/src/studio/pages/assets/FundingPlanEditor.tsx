import { useRef, useState, type FormEvent } from 'react';
import { getAccounts, updateCapsuleFundingSources } from '../../../api';
import type { CapsuleFundingSource, CapsuleFundingSourceInput } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

const loadAssetAccounts = async () => (await getAccounts('asset', true))
    .filter((account) => account.account_type === 'asset' && account.is_active);

interface DraftSource {
    key: string;
    accountId: string;
    amount: string;
    share: string;
}

export function FundingPlanSummary({ total, target, currency }: { total: number; target: number; currency: string }) {
    const difference = total - target;
    // Ignore floating-point noise; a real plan/target mismatch remains advisory.
    const mismatched = Math.abs(difference) > 1e-8;
    return <div className="space-y-1 text-xs" aria-live="polite">
        <p className="flex flex-wrap gap-x-5 gap-y-1 tabular-nums">
            <span>計画合計：{formatCurrency(total, currency)}</span>
            <span>目標額：{formatCurrency(target, currency)}</span>
            <span className={mismatched ? 'text-[var(--studio-warning)]' : ''}>差額（計画合計 − 目標額）：{formatCurrency(difference, currency)}</span>
        </p>
        {mismatched && <p className="text-[var(--studio-warning)]">計画合計と目標額が一致していません。このまま保存できます。</p>}
    </div>;
}

export default function FundingPlanEditor({ capsuleId, sources, target, currency, onSaved, onCancel }: {
    capsuleId: number; sources: CapsuleFundingSource[]; target: number; currency: string;
    onSaved: (sources: CapsuleFundingSource[]) => void; onCancel: () => void;
}) {
    const accounts = useResource(loadAssetAccounts);
    const mutation = useMutation();
    const nextKey = useRef(0);
    const [validationError, setValidationError] = useState('');
    const [rows, setRows] = useState<DraftSource[]>(() => sources.map((source) => ({
        key: `saved-${source.id}`, accountId: String(source.account_id), amount: String(source.target_amount),
        share: source.max_share_bp === null ? '' : String(source.max_share_bp / 100),
    })));
    const updateRow = (key: string, values: Partial<DraftSource>) => {
        setValidationError('');
        setRows((previous) => previous.map((row) => row.key === key ? { ...row, ...values } : row));
    };
    const total = rows.reduce((sum, row) => sum + (Number.isFinite(Number(row.amount)) ? Number(row.amount) : 0), 0);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (accounts.loading || accounts.error || mutation.busy) return;
        const payload: CapsuleFundingSourceInput[] = [];
        const selected = new Set<number>();
        for (const [index, row] of rows.entries()) {
            const accountId = Number(row.accountId);
            const amount = Number(row.amount);
            const share = row.share === '' ? null : Number(row.share);
            if (!accounts.data?.some((account) => account.id === accountId)) {
                setValidationError('口座には有効な資産口座を選択してください。');
                return;
            }
            if (selected.has(accountId)) {
                setValidationError('同じ口座を複数の資金源に指定できません。');
                return;
            }
            if (row.amount === '' || !Number.isFinite(amount) || amount < 0
                || (share !== null && (!Number.isFinite(share) || share < 0 || share > 100
                    || Math.abs(share * 100 - Math.round(share * 100)) > 1e-6))) {
                setValidationError('計画額は0以上、上限は0〜100％（小数第2位まで）で入力してください。');
                return;
            }
            selected.add(accountId);
            // Empty means no cap; an explicit zero must remain a zero-share cap.
            payload.push({ account_id: accountId, target_amount: amount, max_share_bp: share === null ? null : Math.round(share * 100), sort_order: index });
        }
        setValidationError('');
        let savedSources: CapsuleFundingSource[] = [];
        void mutation.run(async () => {
            savedSources = await updateCapsuleFundingSources(capsuleId, payload);
        }, '資金計画を保存しました。', () => onSaved(savedSources));
    };

    return <form onSubmit={submit} className="space-y-4">
        <p className="text-xs text-[var(--studio-text-muted)]">計画額は配分の固定ウェイトです。上限は、その口座の資金をこの取り置きが利用できる最大割合です。同じ口座について、すべての取り置きの上限の合計が100％を超えると保存できません。空欄は上限なし、0％は利用不可です。</p>
        <Feedback loading={accounts.loading} error={validationError || mutation.error || accounts.error} />
        {accounts.error && <button type="button" onClick={accounts.reload} disabled={mutation.busy} className={buttonClass}>口座を再読み込み</button>}
        <fieldset disabled={mutation.busy} className="space-y-3">
            {rows.map((row, index) => <div key={row.key} className="grid items-end gap-3 rounded-md border border-[var(--studio-border)] p-3 md:grid-cols-[2fr_1fr_1fr_auto]">
                <Field label="口座">
                    <select required aria-label={`資金源${index + 1}の口座`} value={row.accountId} onChange={(event) => updateRow(row.key, { accountId: event.target.value })} className={inputClass}>
                        <option value="">口座を選択</option>
                        {/* Preserve an unavailable reference visibly until the user replaces or removes it. */}
                        {row.accountId && !accounts.data?.some((account) => String(account.id) === row.accountId) && <option value={row.accountId} disabled>{sources.find((source) => String(source.account_id) === row.accountId)?.account_name ?? `#${row.accountId}`}（選択できません）</option>}
                        {accounts.data?.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                    </select>
                </Field>
                <Field label={`計画額（${currency}）`}><input required type="number" min="0" step="any" aria-label={`資金源${index + 1}の計画額`} value={row.amount} onChange={(event) => updateRow(row.key, { amount: event.target.value })} className={inputClass} /></Field>
                <Field label="上限（％・任意）"><input type="number" min="0" max="100" step="0.01" placeholder="上限なし" aria-label={`資金源${index + 1}の上限（％）`} value={row.share} onChange={(event) => updateRow(row.key, { share: event.target.value })} className={inputClass} /></Field>
                <button type="button" aria-label={`資金源${index + 1}を削除`} onClick={() => { setValidationError(''); setRows((previous) => previous.filter((item) => item.key !== row.key)); }} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>
            </div>)}
            {!rows.length && <p className="text-xs text-[var(--studio-text-muted)]">資金源はありません。保存すると空の資金計画になります。</p>}
            <button type="button" onClick={() => {
                const key = `new-${nextKey.current++}`;
                setRows((previous) => [...previous, { key, accountId: '', amount: '', share: '' }]);
                setValidationError('');
            }} className={buttonClass}>資金源を追加</button>
        </fieldset>
        <FundingPlanSummary total={total} target={target} currency={currency} />
        <p className="text-xs text-[var(--studio-text-muted)]">保存すると資金計画全体を置き換え、削除した資金源を計画から外します。</p>
        <div className="flex gap-2">
            <button type="submit" disabled={mutation.busy || accounts.loading || Boolean(accounts.error)} className={primaryClass}>{mutation.busy ? '保存中…' : '保存'}</button>
            <button type="button" disabled={mutation.busy} onClick={onCancel} className={buttonClass}>キャンセル</button>
        </div>
    </form>;
}
