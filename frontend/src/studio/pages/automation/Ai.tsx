import Overlay from '../../components/Overlay';
import { DataTable, Feedback } from '../db/Database';
import { useRef, useState } from 'react';
import { getAiExecutionSettings, getAiPolicies, updateAiExecutionSettings, updateAiPolicies } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiExecutionSettings, AiOperationMode, AiOperationPolicy, AiOperationPolicyPayload } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { buttonClass, inputClass, MODE_LABELS, RISK_LABELS } from './labels';
import { primaryClass } from '../db/forms';
import { tr } from '../../i18n';

type PolicyEdit = Pick<AiOperationPolicy, 'mode' | 'require_mfa'>;

function policyPayload(row: AiOperationPolicy): AiOperationPolicyPayload {
    // The replacement API needs every policy, but server identity fields are not writable.
    return {
        ai_client_id: row.ai_client_id, resource: row.resource, action: row.action, risk: row.risk,
        mode: row.mode, threshold_amount: row.threshold_amount, threshold_count: row.threshold_count,
        require_mfa: row.require_mfa,
    };
}

function Policies({ currency }: { currency: string }) {
    const { data, setData, loading, error } = useResource(getAiPolicies);
    const [editing, setEditing] = useState(false);
    const [edits, setEdits] = useState<Record<number, PolicyEdit>>({});
    const [saving, setSaving] = useState(false);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const rows = data?.map((row) => ({ ...row, ...edits[row.id] })) ?? [];
    const changed = data?.filter((row) => {
        const edit = edits[row.id];
        return edit && (edit.mode !== row.mode || edit.require_mfa !== row.require_mfa);
    }).length ?? 0;

    const editRow = (row: AiOperationPolicy, patch: Partial<PolicyEdit>) => {
        setEdits((previous) => ({ ...previous, [row.id]: { mode: row.mode, require_mfa: row.require_mfa, ...patch } }));
        setConfirmation('');
    };
    const save = async () => {
        if (inFlight.current || loading || error || !data || !changed) return;
        inFlight.current = true;
        setSaving(true);
        setOperationError('');
        setConfirmation('');
        try {
            const updated = await updateAiPolicies(rows.map(policyPayload));
            setData(updated);
            setEdits({});
            setEditing(false);
            setConfirmation(tr(`${changed}行の権限ルールを保存しました。`, `Saved ${changed} permission rule(s).`));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            inFlight.current = false;
            setSaving(false);
        }
    };

    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">{tr('AI操作の権限ルール', 'AI operation permissions')}</h2>
                <div className="flex gap-2"><button type="button" disabled={loading || saving || Boolean(error) || !data?.length} onClick={() => setEditing(true)} className={buttonClass}>{tr('権限ルールを編集', 'Edit permissions')}</button></div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('権限ルールを読み込んでいます…', 'Loading permissions…')}</p>}
            {(error || operationError) && <p role="alert" className="text-sm text-[var(--studio-danger)]">{error || operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && <DataTable columns={[tr('対象', 'Resource'), tr('操作', 'Operation'), tr('権限ルール', 'Permission'), tr('リスク', 'Risk')]}>
                {data.length ? data.map((row) => <tr key={row.id}>
                    <th scope="row" className="px-5 py-3 font-medium">{row.resource}<span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{row.ai_client_id == null ? tr('すべてのAIクライアント', 'All AI clients') : tr(`AIクライアント #${row.ai_client_id}`, `AI client #${row.ai_client_id}`)}</span></th>
                    <td className="px-5 py-3">{row.action}</td>
                    <td className="space-y-2 px-5 py-3"><p>{MODE_LABELS[row.mode]}{row.require_mfa && tr(' ／ MFAを必須にする', ' / MFA required')}</p>
                        {row.threshold_amount != null && <p className="text-xs text-[var(--studio-text-muted)]">{tr(`金額条件：${formatCurrency(row.threshold_amount, currency)}（${currency}）`, `Amount threshold: ${formatCurrency(row.threshold_amount, currency)} (${currency})`)}</p>}
                        {row.threshold_count != null && <p className="text-xs text-[var(--studio-text-muted)]">{tr(`件数条件：${row.threshold_count}件`, `Count threshold: ${row.threshold_count}`)}</p>}
                    </td><td className="px-5 py-3">{RISK_LABELS[row.risk]}</td>
                </tr>) : <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('登録された権限ルールはありません。', 'No permission rules.')}</td></tr>}
            </DataTable>}
            {editing && <Overlay title={tr('AI操作の権限ルールを編集', 'Edit AI operation permissions')} footer={<button type="button" onClick={() => void save()} disabled={loading || saving || Boolean(error) || !changed} className={primaryClass}>{saving ? tr('保存中…', 'Saving…') : tr('保存', 'Save')}</button>} onClose={() => { setEditing(false); setEdits({}); }}>
                <Feedback error={operationError || error} />
            {data && (rows.length ? (
                <fieldset disabled={loading || saving || Boolean(error)}>
                    <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                        <table className="w-full text-left text-sm" aria-busy={loading || saving}>
                            <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                                <tr>{[tr('対象', 'Resource'), tr('操作', 'Operation'), tr('権限ルール', 'Permission'), tr('リスク', 'Risk')].map((label) => <th scope="col" key={label} className="px-5 py-3 font-medium">{label}</th>)}</tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--studio-border)]">
                                {rows.map((row) => (
                                    <tr key={row.id}>
                                        <th scope="row" className="px-5 py-3 font-medium">
                                            {row.resource}
                                            <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{row.ai_client_id == null ? tr('すべてのAIクライアント', 'All AI clients') : tr(`AIクライアント #${row.ai_client_id}`, `AI client #${row.ai_client_id}`)}</span>
                                        </th>
                                        <td className="px-5 py-3">{row.action}</td>
                                        <td className="space-y-2 px-5 py-3">
                                            <select aria-label={tr(`${row.resource}・${row.action}・${RISK_LABELS[row.risk]}の権限ルール`, `Permission for ${row.resource} ${row.action} (${RISK_LABELS[row.risk]})`)} value={row.mode} onChange={(event) => editRow(row, { mode: event.target.value as AiOperationMode })} className={inputClass}>
                                                {Object.entries(MODE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                            </select>
                                            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={row.require_mfa} onChange={(event) => editRow(row, { require_mfa: event.target.checked })} />{tr('MFAを必須にする', 'Require MFA')}</label>
                                            {row.threshold_amount != null && <p className="text-xs text-[var(--studio-text-muted)]">{tr(`金額条件：${formatCurrency(row.threshold_amount, currency)}（${currency}）`, `Amount threshold: ${formatCurrency(row.threshold_amount, currency)} (${currency})`)}</p>}
                                            {row.threshold_count != null && <p className="text-xs text-[var(--studio-text-muted)]">{tr(`件数条件：${row.threshold_count}件`, `Count threshold: ${row.threshold_count}`)}</p>}
                                        </td>
                                        <td className="whitespace-nowrap px-5 py-3">{RISK_LABELS[row.risk]}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </fieldset>
            ) : <p className="text-sm text-[var(--studio-text-muted)]">{tr('登録された権限ルールはありません。', 'No permission rules.')}</p>)}
            <div className="flex items-center gap-3">
                <span role="status" className="text-xs text-[var(--studio-text-muted)]">{tr(`変更した行：${changed}行`, `Changed rows: ${changed}`)}</span>
                {changed > 0 && <button type="button" onClick={() => { setEdits({}); setOperationError(''); }} disabled={saving} className={buttonClass}>{tr('変更を戻す', 'Undo changes')}</button>}
            </div>
            </Overlay>}
        </section>
    );
}

function ExecutionSettings() {
    const { data, setData, loading, error } = useResource(getAiExecutionSettings);
    const [editing, setEditing] = useState(false);
    const [mode, setMode] = useState<AiExecutionSettings['mcp_write_mode'] | null>(null);
    const [saving, setSaving] = useState(false);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const changed = data !== null && mode !== null && mode !== data.mcp_write_mode;
    const save = async () => {
        if (inFlight.current || loading || error || !data || !mode || !changed) return;
        inFlight.current = true;
        setSaving(true);
        setOperationError('');
        setConfirmation('');
        try {
            // Supported operations are server capabilities, so only the write mode is edited.
            setData(await updateAiExecutionSettings({ ...data, mcp_write_mode: mode }));
            setMode(null);
            setEditing(false);
            setConfirmation(tr('実行設定を保存しました。', 'Execution settings saved.'));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            inFlight.current = false;
            setSaving(false);
        }
    };
    return (
        <>
        <button type="button" disabled={loading || saving} onClick={() => setEditing(true)} className={buttonClass}>{tr('AI実行設定', 'AI execution settings')}</button>
        {!editing && <Feedback error={error || operationError} message={confirmation} />}
        {editing && <Overlay title={tr('AI実行設定', 'AI execution settings')} footer={<button type="button" onClick={() => void save()} disabled={loading || saving || Boolean(error) || !changed} className={primaryClass}>{saving ? tr('保存中…', 'Saving…') : tr('実行設定を保存', 'Save execution settings')}</button>} onClose={() => { setEditing(false); setMode(null); }}><section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('実行設定を読み込んでいます…', 'Loading execution settings…')}</p>}
            {(error || operationError) && <p role="alert" className="text-sm text-[var(--studio-danger)]">{error || operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && <>
                <label className="flex flex-wrap items-center gap-3 text-sm">{tr('MCPの書き込み方式', 'MCP writes')}
                    <select value={mode ?? data.mcp_write_mode} disabled={loading || saving || Boolean(error)} onChange={(event) => { setMode(event.target.value as AiExecutionSettings['mcp_write_mode']); setConfirmation(''); }} className={inputClass}>
                        <option value="direct_write">{tr('直接書き込み', 'Write directly')}</option><option value="change_request">{tr('承認リクエスト経由', 'Through approval requests')}</option>
                    </select>
                </label>
                <p className="text-xs text-[var(--studio-text-muted)]">{tr('承認リクエストに対応する操作（参照のみ）', 'Operations that support approval requests (read only)')}</p>
                {data.supported_change_request_operations.length ? <ul className="space-y-1 text-xs">{data.supported_change_request_operations.map((operation) => <li key={operation}>{operation}</li>)}</ul> : <p className="text-xs text-[var(--studio-text-muted)]">{tr('対応する操作はありません。', 'None.')}</p>}
            </>}
        </section></Overlay>}
        </>
    );
}

function AiForClient({ currency }: { currency: string }) {
    return <div className="space-y-8"><Policies currency={currency} /><ExecutionSettings /></div>;
}

export default function Ai() {
    const { clientId, currentClient } = useClient();
    // A client switch must discard both unsaved rules and responses from the previous client.
    return <AiForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
