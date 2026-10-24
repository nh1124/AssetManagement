import { Settings } from 'lucide-react';
import Overlay from '../../components/Overlay';
import { DataTable, Feedback } from '../db/Database';
import { useRef, useState } from 'react';
import { endMcpConnection, getAiExecutionSettings, getAiPolicies, getMcpConnections, updateAiExecutionSettings, updateAiPolicies } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiExecutionSettings, AiOperationMode, AiOperationPolicy, AiOperationRisk, McpConnection } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { buttonClass, inputClass, MODE_LABELS, RISK_LABELS } from './labels';
import { primaryClass } from '../db/forms';
import { tr } from '../../i18n';
import { Help } from '../../components/Help';
import { useConfirm } from '../../components/useConfirm';
import { formatDate, formatDateTime, useTimezone } from '../../datetime';
import { newPolicyDefaults, newPolicyPayload, newPolicyProblem, policyPayload, POLICY_ACTIONS, POLICY_RESOURCES, type NewPolicy } from './policyRules';

type PolicyEdit = Pick<AiOperationPolicy, 'mode' | 'require_mfa'>;
type WriteMode = AiExecutionSettings['mcp_write_mode'];

const WRITE_MODE_LABELS: Record<WriteMode, () => string> = {
    direct_write: () => tr('直接書き込み', 'Write directly'),
    change_request: () => tr('承認リクエスト経由', 'Through approval requests'),
};
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

function appName(row: McpConnection) {
    return row.client_name || row.oauth_client_id;
}

/** The AI apps this person connected over MCP, how to connect one, and ending a connection (WP35). */
function Connections() {
    const { data, setData, loading, error } = useResource(getMcpConnections);
    const confirm = useConfirm();
    const timezone = useTimezone();
    const [ending, setEnding] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const [copyStatus, setCopyStatus] = useState<'copied' | 'failed' | null>(null);
    const command = data?.mcp_url ? `claude mcp add --transport http --scope user asset-management ${data.mcp_url}` : '';
    const copy = async (text: string) => {
        try {
            await navigator.clipboard.writeText(text);
            setCopyStatus('copied');
        } catch { setCopyStatus('failed'); }
    };
    const end = async (row: McpConnection) => {
        if (ending !== null || !data) return;
        const accepted = await confirm(
            tr(`「${appName(row)}」の接続を切断します。このアプリは次の操作から使えなくなり、使うにはもう一度接続（ログイン）が要ります。`,
                `Disconnect “${appName(row)}”? The app stops working from its next operation and has to connect (sign in) again.`),
            tr('切断', 'Disconnect'));
        if (!accepted) return;
        setEnding(row.id);
        setOperationError('');
        setConfirmation('');
        try {
            await endMcpConnection(row.id);
            setData({ ...data, connections: data.connections.filter((other) => other.id !== row.id) });
            setConfirmation(tr(`「${appName(row)}」の接続を切断しました。`, `Disconnected “${appName(row)}”.`));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            setEnding(null);
        }
    };

    return (
        <section className="space-y-4">
            <h2 className="flex items-center gap-1.5 text-lg font-semibold">{tr('AIアプリの接続', 'AI app connections')}
                <Help label={tr('AIアプリの接続', 'AI app connections')} text={tr('MCP で繋いだ AI アプリ（Claude Code など）の一覧です。接続は、アプリのログイン画面であなたがユーザー名・パスワード・認証コードを入れて許可したときにできます。切断すると、そのアプリは次の操作から使えなくなります。パスワードの変更や全端末からのサインアウトの後は、すべての接続が「再接続が必要」になります。', 'The AI apps (such as Claude Code) connected over MCP. A connection is made when you allow it on the app’s sign-in page with your username, password and authenticator code. A disconnected app stops working from its next operation. After a password change or a sign-out everywhere, every connection needs to reconnect.')} wide />
            </h2>
            <Feedback loading={loading} error={error || operationError} message={confirmation} />
            {data && <>
                <div className="space-y-2 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4 text-sm">
                    <p className="flex items-center gap-1.5 font-semibold">{tr('接続の手順', 'How to connect')}
                        <Help label={tr('接続の手順', 'How to connect')} text={tr('ほかの AI アプリでは、MCP サーバーの URL を「リモート MCP サーバー」や「コネクタ」として登録します。繋がらないときは、アプリが表示するエラーを確認してください（invalid_client：アプリの登録が見つからない、invalid_redirect_uri：戻り先が登録と違う、invalid_target：別のサーバー宛て）。', 'In other AI apps, add the MCP server URL as a remote MCP server or connector. If it does not connect, check the error the app shows (invalid_client: the app’s registration was not found; invalid_redirect_uri: the return address differs from the registration; invalid_target: meant for another server).')} wide />
                    </p>
                    <ol className="list-decimal space-y-2 pl-5">
                        <li>{tr('Claude Code では、ターミナルで次のコマンドを実行します。', 'In Claude Code, run this command in a terminal.')}
                            <span className="mt-1 flex flex-wrap items-center gap-2"><code className="select-all break-all font-mono text-xs">{command}</code>
                                <button type="button" onClick={() => void copy(command)} disabled={!command} className={buttonClass}>{tr('コピー', 'Copy')}</button></span>
                        </li>
                        <li>{tr('ほかのアプリでは、MCP サーバーの URL を登録します。', 'In other apps, add the MCP server URL.')}
                            <span className="mt-1 flex flex-wrap items-center gap-2"><code className="select-all break-all font-mono text-xs">{data.mcp_url}</code>
                                <button type="button" onClick={() => void copy(data.mcp_url)} disabled={!data.mcp_url} className={buttonClass}>{tr('コピー', 'Copy')}</button></span>
                        </li>
                        <li>{tr('アプリが開くログイン画面で、このアプリのユーザー名・パスワード・認証コードを入れて許可します。', 'On the sign-in page the app opens, enter your username, password and authenticator code for this app, and allow it.')}</li>
                    </ol>
                    {copyStatus && <p role={copyStatus === 'failed' ? 'alert' : 'status'} className="text-xs">{copyStatus === 'copied' ? tr('コピーしました。', 'Copied.') : tr('コピーできません。選んでコピーしてください。', 'Could not copy. Select the text and copy it.')}</p>}
                </div>
                <DataTable columns={[tr('アプリ', 'App'), tr('アプリの情報', 'App information'), tr('戻り先', 'Returns to'), tr('接続した日時', 'Connected'), tr('最後に使った日時', 'Last used'), tr('状態', 'Status'), tr('操作', 'Action')]}>
                    {data.connections.length ? data.connections.map((row) => <tr key={row.id}>
                        <th scope="row" className="px-5 py-3 font-medium">{appName(row)}<span className="mt-1 block break-all text-xs font-normal text-[var(--studio-text-muted)]">{row.oauth_client_id}</span></th>
                        <td className="px-5 py-3">{row.client_source === 'cimd'
                            ? tr(`公開された情報（${row.client_host ?? ''}）`, `Published by ${row.client_host ?? ''}`)
                            : tr('このサーバーに登録', 'Registered with this server')}</td>
                        <td className="px-5 py-3">{row.redirect_host && LOOPBACK_HOSTS.has(row.redirect_host)
                            ? tr(`このコンピューター（${row.redirect_host}）`, `This computer (${row.redirect_host})`)
                            : row.redirect_host ?? '—'}</td>
                        <td className="whitespace-nowrap px-5 py-3 text-xs"><time dateTime={row.connected_at}>{formatDateTime(row.connected_at, timezone)}</time></td>
                        <td className="whitespace-nowrap px-5 py-3 text-xs">{row.last_used_at ? <time dateTime={row.last_used_at}>{formatDateTime(row.last_used_at, timezone)}</time> : '—'}</td>
                        <td className="px-5 py-3">{row.status === 'active' ? tr('有効', 'Active') : <span className="text-[var(--studio-danger)]">{tr('再接続が必要', 'Reconnect required')}</span>}
                            <span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{row.refreshable
                                ? tr(`${formatDate(row.expires_at, timezone)}まで（使うと延長）`, `Until ${formatDate(row.expires_at, timezone)} (extended when used)`)
                                : tr(`${formatDateTime(row.expires_at, timezone)}まで`, `Until ${formatDateTime(row.expires_at, timezone)}`)}</span>
                        </td>
                        <td className="px-5 py-3"><button type="button" onClick={() => void end(row)} disabled={ending !== null} className={buttonClass}>{ending === row.id ? tr('切断中…', 'Disconnecting…') : tr('切断', 'Disconnect')}</button></td>
                    </tr>) : <tr><td colSpan={7} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('接続している AI アプリはありません。', 'No AI apps are connected.')}</td></tr>}
                </DataTable>
            </>}
        </section>
    );
}

/** What the AI may do: the MCP write mode and the permission rules, edited together behind ⚙ (owner 2026-10-24, C6). */
function Permissions({ currency }: { currency: string }) {
    const policies = useResource(getAiPolicies);
    const settings = useResource(getAiExecutionSettings);
    const [editing, setEditing] = useState(false);
    const [mode, setMode] = useState<WriteMode | null>(null);
    const [edits, setEdits] = useState<Record<number, PolicyEdit>>({});
    const [added, setAdded] = useState<NewPolicy[]>([]);
    const [draft, setDraft] = useState<NewPolicy>(newPolicyDefaults);
    const [saving, setSaving] = useState(false);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const loading = policies.loading || settings.loading;
    const error = policies.error || settings.error;
    const data = policies.data;
    const rows = data?.map((row) => ({ ...row, ...edits[row.id] })) ?? [];
    const rulesChanged = (data?.filter((row) => {
        const edit = edits[row.id];
        return edit && (edit.mode !== row.mode || edit.require_mfa !== row.require_mfa);
    }).length ?? 0) + added.length;
    const modeChanged = settings.data !== null && mode !== null && mode !== settings.data.mcp_write_mode;
    const changed = rulesChanged + (modeChanged ? 1 : 0);
    const draftProblem = newPolicyProblem(draft, [...rows, ...added.map(newPolicyPayload)]);

    const editRow = (row: AiOperationPolicy, patch: Partial<PolicyEdit>) => {
        setEdits((previous) => ({ ...previous, [row.id]: { mode: row.mode, require_mfa: row.require_mfa, ...patch } }));
        setConfirmation('');
    };
    const addRule = () => {
        if (draftProblem) return;
        setAdded((previous) => [...previous, draft]);
        setDraft(newPolicyDefaults());
        setConfirmation('');
    };
    const discard = () => {
        setMode(null);
        setEdits({});
        setAdded([]);
        setDraft(newPolicyDefaults());
    };
    const save = async () => {
        if (inFlight.current || loading || error || !data || !settings.data || !changed) return;
        inFlight.current = true;
        setSaving(true);
        setOperationError('');
        setConfirmation('');
        try {
            // Supported operations are server capabilities, so only the write mode is edited.
            if (modeChanged && mode) {
                settings.setData(await updateAiExecutionSettings({ ...settings.data, mcp_write_mode: mode }));
                setMode(null);
            }
            if (rulesChanged) {
                policies.setData(await updateAiPolicies([...rows.map(policyPayload), ...added.map(newPolicyPayload)]));
            }
            discard();
            setEditing(false);
            setConfirmation(tr('AIの実行設定と権限ルールを保存しました。', 'Saved the AI execution settings and permissions.'));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            inFlight.current = false;
            setSaving(false);
        }
    };
    const editLabel = tr('AIの実行設定と権限ルールを編集', 'Edit AI execution settings and permissions');

    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">{tr('AI操作の権限', 'AI operation permissions')}</h2>
                <button type="button" disabled={loading || saving || Boolean(error) || !data || !settings.data} onClick={() => setEditing(true)} aria-label={editLabel} title={editLabel}
                    className={`${buttonClass} inline-flex items-center`}><Settings size={16} aria-hidden="true" /></button>
            </div>
            {!editing && <Feedback loading={loading} error={error || operationError} message={confirmation} />}
            {settings.data && <p className="text-sm">{tr('MCPの書き込み方式：', 'MCP writes: ')}<strong>{WRITE_MODE_LABELS[settings.data.mcp_write_mode]()}</strong></p>}
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
            {editing && <Overlay title={tr('AIの実行設定と権限ルール', 'AI execution settings and permissions')} footer={<button type="button" onClick={() => void save()} disabled={loading || saving || Boolean(error) || !changed} className={primaryClass}>{saving ? tr('保存中…', 'Saving…') : tr('保存', 'Save')}</button>} onClose={() => { setEditing(false); discard(); }}>
                <Feedback error={operationError || error} />
                {settings.data && <fieldset disabled={loading || saving || Boolean(error)} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
                    <legend className="px-1 text-sm font-semibold">{tr('実行設定', 'Execution settings')}</legend>
                    <label className="flex flex-wrap items-center gap-3 text-sm">{tr('MCPの書き込み方式', 'MCP writes')}
                        <select value={mode ?? settings.data.mcp_write_mode} onChange={(event) => { setMode(event.target.value as WriteMode); setConfirmation(''); }} className={inputClass}>
                            {(Object.keys(WRITE_MODE_LABELS) as WriteMode[]).map((value) => <option key={value} value={value}>{WRITE_MODE_LABELS[value]()}</option>)}
                        </select>
                    </label>
                    <p className="text-xs text-[var(--studio-text-muted)]">{tr('承認リクエストに対応する操作（参照のみ）', 'Operations that support approval requests (read only)')}</p>
                    {settings.data.supported_change_request_operations.length ? <ul className="space-y-1 text-xs">{settings.data.supported_change_request_operations.map((operation) => <li key={operation}>{operation}</li>)}</ul> : <p className="text-xs text-[var(--studio-text-muted)]">{tr('対応する操作はありません。', 'None.')}</p>}
                </fieldset>}
            {data && (rows.length || added.length ? (
                <fieldset disabled={loading || saving || Boolean(error)}>
                    <legend className="mb-2 px-1 text-sm font-semibold">{tr('権限ルール', 'Permission rules')}</legend>
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
                                {added.map((rule, index) => (
                                    <tr key={`added-${index}`}>
                                        <th scope="row" className="px-5 py-3 font-medium">
                                            {rule.resource.trim().toLowerCase()}
                                            <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{tr('すべてのAIクライアント・未保存', 'All AI clients · not saved')}</span>
                                        </th>
                                        <td className="px-5 py-3">{rule.action.trim().toLowerCase()}</td>
                                        <td className="space-y-2 px-5 py-3"><p>{MODE_LABELS[rule.mode]}{rule.require_mfa && tr(' ／ MFAを必須にする', ' / MFA required')}</p>
                                            <button type="button" onClick={() => setAdded((previous) => previous.filter((_, other) => other !== index))} className={buttonClass}>{tr('追加を取り消す', 'Remove')}</button>
                                        </td>
                                        <td className="whitespace-nowrap px-5 py-3">{RISK_LABELS[rule.risk]}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </fieldset>
            ) : <p className="text-sm text-[var(--studio-text-muted)]">{tr('登録された権限ルールはありません。', 'No permission rules.')}</p>)}
            {data && <fieldset disabled={loading || saving || Boolean(error)} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
                <legend className="flex items-center gap-1.5 px-1 text-sm font-semibold">{tr('権限ルールを追加', 'Add a permission rule')}
                    <Help label={tr('権限ルールを追加', 'Add a permission rule')} text={tr('ルールの無い操作は既定の扱いになります（読み取りは許可、書き込みは承認が必要）。AIがMCPから帳簿へ直接書き込むには、MCPの書き込み方式を「直接書き込み」にし、transactions・create・中 を「実行を許可」にします。追加したルールはすべてのAIクライアントに効きます。', 'Operations without a rule follow the defaults (reads allowed, writes need approval). For the AI to write the ledger directly over MCP, set MCP writes to “Write directly” and transactions · create · Medium to “Allow”. An added rule applies to every AI client.')} wide />
                </legend>
                <div className="flex flex-wrap items-end gap-3 text-sm">
                    <label className="flex flex-col gap-1">{tr('対象', 'Resource')}
                        <input value={draft.resource} list="ai-policy-resources" onChange={(event) => setDraft({ ...draft, resource: event.target.value })} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1">{tr('操作', 'Operation')}
                        <input value={draft.action} list="ai-policy-actions" onChange={(event) => setDraft({ ...draft, action: event.target.value })} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1">{tr('リスク', 'Risk')}
                        <select value={draft.risk} onChange={(event) => setDraft({ ...draft, risk: event.target.value as AiOperationRisk })} className={inputClass}>
                            {Object.entries(RISK_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                    </label>
                    <label className="flex flex-col gap-1">{tr('権限ルール', 'Permission')}
                        <select value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value as AiOperationMode })} className={inputClass}>
                            {Object.entries(MODE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                    </label>
                    <label className="flex items-center gap-2 py-2 text-xs"><input type="checkbox" checked={draft.require_mfa} onChange={(event) => setDraft({ ...draft, require_mfa: event.target.checked })} />{tr('MFAを必須にする', 'Require MFA')}</label>
                    <button type="button" onClick={addRule} disabled={Boolean(draftProblem)} className={buttonClass}>{tr('追加', 'Add')}</button>
                </div>
                <datalist id="ai-policy-resources">{POLICY_RESOURCES.map((resource) => <option key={resource} value={resource} />)}</datalist>
                <datalist id="ai-policy-actions">{POLICY_ACTIONS.map((action) => <option key={action} value={action} />)}</datalist>
                {draftProblem === 'missing' && <p className="text-xs text-[var(--studio-text-muted)]">{tr('対象と操作を入力してください。', 'Enter a resource and an operation.')}</p>}
                {draftProblem === 'duplicate' && <p role="alert" className="text-xs text-[var(--studio-danger)]">{tr('同じ対象・操作・リスクのルールがあります。上の表で変更してください。', 'A rule for this resource, operation and risk exists. Change it in the table above.')}</p>}
            </fieldset>}
            <div className="flex items-center gap-3">
                <span role="status" className="text-xs text-[var(--studio-text-muted)]">{tr(`変更した項目：${changed}件`, `Changed items: ${changed}`)}</span>
                {changed > 0 && <button type="button" onClick={() => { discard(); setOperationError(''); }} disabled={saving} className={buttonClass}>{tr('変更を戻す', 'Undo changes')}</button>}
            </div>
            </Overlay>}
        </section>
    );
}

function AiForClient({ currency }: { currency: string }) {
    return <div className="space-y-8"><Connections /><Permissions currency={currency} /></div>;
}

export default function Ai() {
    const { clientId, currentClient } = useClient();
    // A client switch must discard both unsaved rules and responses from the previous client.
    return <AiForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
