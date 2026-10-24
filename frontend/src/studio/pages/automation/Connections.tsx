import { useId, useState, type ReactNode } from 'react';
import { endMcpConnection, getMcpConnections } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { McpConnection } from '../../../types';
import Overlay from '../../components/Overlay';
import { Help } from '../../components/Help';
import { useConfirm } from '../../components/useConfirm';
import { formatDate, formatDateTime, useTimezone } from '../../datetime';
import { tr } from '../../i18n';
import { assetErrorMessage, useResource } from '../../useResource';
import { DataTable, EditableRow } from '../db/Database';
import { buttonClass } from './labels';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);
const dangerClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-danger)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';
const pillClass = 'whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium';

function appName(row: McpConnection) {
    return row.client_name || row.oauth_client_id;
}

function StatusPill({ row }: { row: McpConnection }) {
    return row.status === 'active'
        ? <span className={`${pillClass} border-[var(--studio-positive)] text-[var(--studio-positive)]`}>{tr('有効', 'Active')}</span>
        : <span className={`${pillClass} border-[var(--studio-danger)] text-[var(--studio-danger)]`}>{tr('再接続が必要', 'Reconnect required')}</span>;
}

/** A value to copy, with its copy button and the result beside the button. */
function CopyField({ text, label }: { text: string; label: string }) {
    const [copied, setCopied] = useState<boolean | null>(null);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
        } catch { setCopied(false); }
    };
    return <div className="space-y-2">
        <code className="block select-all break-all rounded-md bg-[var(--studio-bg)] px-3 py-2 font-mono text-xs">{text}</code>
        <span className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => void copy()} className={buttonClass}>{label}</button>
            {copied !== null && <span role={copied ? 'status' : 'alert'} className={`text-xs ${copied ? 'text-[var(--studio-positive)]' : 'text-[var(--studio-danger)]'}`}>{copied ? tr('コピーしました', 'Copied') : tr('コピーできません。選んでコピーしてください。', 'Could not copy. Select the text and copy it.')}</span>}
        </span>
    </div>;
}

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
    return <li className="flex gap-3">
        <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--studio-accent)] text-xs font-medium text-[var(--studio-accent-text)]">{number}</span>
        <div className="min-w-0 flex-1 space-y-2"><p className="text-sm font-medium">{title}</p>{children}</div>
    </li>;
}

type AppKind = 'claude_code' | 'other';

const troubleshooting = () => tr('繋がらないときは、アプリが表示するエラーを確認してください（invalid_client：アプリの登録が見つからない、invalid_redirect_uri：戻り先が登録と違う、invalid_target：別のサーバー宛て）。', 'If it does not connect, check the error the app shows (invalid_client: the app’s registration was not found; invalid_redirect_uri: the return address differs from the registration; invalid_target: meant for another server).');

/** How to connect an AI app, in three numbered steps: in the overlay (titled by it), and in place of the table while nothing is connected. */
function ConnectSteps({ mcpUrl, onRefresh, heading = false }: { mcpUrl: string; onRefresh: () => void; heading?: boolean }) {
    const [app, setApp] = useState<AppKind>('claude_code');
    const tabs = useId();
    const title = tr('接続の手順', 'How to connect');
    const kinds: Array<[AppKind, string]> = [['claude_code', 'Claude Code'], ['other', tr('ほかのアプリ', 'Other apps')]];
    return <div className="space-y-4">
        {heading && <p className="flex items-center gap-1.5 text-sm font-semibold">{title}<Help label={title} text={troubleshooting()} wide /></p>}
        <ol className="space-y-5">
            <Step number={1} title={tr('接続先を登録', 'Add the server')}>
                {mcpUrl ? <>
                    <div role="tablist" aria-label={tr('使うアプリ', 'Your app')} className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)] text-xs">
                        {kinds.map(([kind, label]) => <button key={kind} type="button" role="tab" id={`${tabs}-${kind}`} aria-selected={app === kind} aria-controls={`${tabs}-panel`} onClick={() => setApp(kind)}
                            className={`border-l border-[var(--studio-border)] px-3 py-1.5 first:border-l-0 ${app === kind ? 'bg-[var(--studio-accent)] font-medium text-[var(--studio-accent-text)]' : 'text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)]'}`}>{label}</button>)}
                    </div>
                    <div role="tabpanel" id={`${tabs}-panel`} aria-labelledby={`${tabs}-${app}`}>
                        {app === 'claude_code'
                            ? <CopyField key="command" text={`claude mcp add --transport http --scope user asset-management ${mcpUrl}`} label={tr('コマンドをコピー', 'Copy the command')} />
                            : <CopyField key="url" text={mcpUrl} label={tr('URL をコピー', 'Copy the URL')} />}
                    </div>
                </> : <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('接続先の URL が設定されていません。', 'The server URL is not set.')}</p>}
            </Step>
            <Step number={2} title={tr('ログインして許可', 'Sign in and allow')}>
                <p className="text-xs text-[var(--studio-text-muted)]">{tr('アプリが開く画面で、ここと同じユーザー名・パスワード・認証コードを入れます。', 'On the page the app opens, use the same username, password and authenticator code as here.')}</p>
            </Step>
            <Step number={3} title={tr('確かめる', 'Check')}>
                <button type="button" onClick={onRefresh} className={buttonClass}>{tr('一覧を更新', 'Refresh the list')}</button>
            </Step>
        </ol>
    </div>;
}

/** One connection in full, and where it is ended. */
function ConnectionDetails({ row, ending, onEnd, onClose }: { row: McpConnection; ending: boolean; onEnd: () => void; onClose: () => void }) {
    const timezone = useTimezone();
    const facts: Array<[string, ReactNode]> = [
        [tr('状態', 'Status'), <StatusPill row={row} />],
        [tr('期限', 'Expires'), row.refreshable
            ? tr(`${formatDate(row.expires_at, timezone)}（使うと延長）`, `${formatDate(row.expires_at, timezone)} (extended when used)`)
            : formatDateTime(row.expires_at, timezone)],
        [tr('接続した日時', 'Connected'), formatDateTime(row.connected_at, timezone)],
        [tr('最終利用', 'Last used'), row.last_used_at ? formatDateTime(row.last_used_at, timezone) : '—'],
        [tr('提供元', 'Published by'), row.client_source === 'cimd' ? row.client_host ?? '—' : tr('このサーバーに登録したアプリ', 'Registered with this server')],
        [tr('戻り先', 'Returns to'), row.redirect_host && LOOPBACK_HOSTS.has(row.redirect_host)
            ? tr(`このコンピューター（${row.redirect_host}）`, `This computer (${row.redirect_host})`)
            : row.redirect_host ?? '—'],
        [tr('アプリの ID', 'App ID'), <span className="break-all font-mono text-xs">{row.oauth_client_id}</span>],
    ];
    return <Overlay title={appName(row)} busy={ending} onClose={onClose}
        footer={<button type="button" onClick={onEnd} disabled={ending} className={`${dangerClass} mr-auto`}>{ending ? tr('切断中…', 'Disconnecting…') : tr('切断', 'Disconnect')}</button>}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-3 text-sm">
            {facts.map(([label, value]) => <div key={label} className="contents"><dt className="text-[var(--studio-text-muted)]">{label}</dt><dd className="min-w-0">{value}</dd></div>)}
        </dl>
    </Overlay>;
}

/** The AI apps this person connected over MCP, how to connect one, and ending a connection (WP35; own page WP36; WP37). */
function ConnectionsForClient() {
    const { data, setData, loading, error, reload } = useResource(getMcpConnections);
    const confirm = useConfirm();
    const timezone = useTimezone();
    const [showSteps, setShowSteps] = useState(false);
    const [selected, setSelected] = useState<McpConnection | null>(null);
    const [ending, setEnding] = useState(false);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const refresh = () => {
        setShowSteps(false);
        setOperationError('');
        setConfirmation('');
        reload();
    };
    const end = async (row: McpConnection) => {
        if (ending || !data) return;
        const accepted = await confirm(
            tr(`「${appName(row)}」を切断します。このアプリを使うには、もう一度接続が要ります。`,
                `Disconnect “${appName(row)}”? Using the app again needs a new connection.`),
            tr('切断', 'Disconnect'));
        if (!accepted) return;
        setEnding(true);
        setOperationError('');
        setConfirmation('');
        try {
            await endMcpConnection(row.id);
            setData({ ...data, connections: data.connections.filter((other) => other.id !== row.id) });
            setSelected(null);
            setConfirmation(tr(`「${appName(row)}」を切断しました。`, `Disconnected “${appName(row)}”.`));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            setEnding(false);
        }
    };
    const connections = data && !loading && !error ? data.connections : null;

    return (
        <section className="space-y-4">
            {connections && connections.length > 0 && <div className="flex justify-end">
                <button type="button" aria-haspopup="dialog" onClick={() => setShowSteps(true)} className={buttonClass}>{tr('接続方法', 'How to connect')}</button>
            </div>}
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
            {error && <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--studio-danger)]">{tr(`接続の一覧を取得できませんでした。${error}`, `Could not load the connections. ${error}`)}
                <button type="button" onClick={refresh} className={buttonClass}>{tr('再読み込み', 'Reload')}</button></p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {connections && (connections.length ? (
                <DataTable columns={[tr('アプリ', 'App'), tr('最終利用', 'Last used'), tr('状態', 'Status')]}>
                    {connections.map((row) => <EditableRow key={row.id} disabled={ending} onEdit={() => setSelected(row)}>
                        <th scope="row" className="px-5 py-3 font-medium">
                            <button type="button" aria-haspopup="dialog" aria-label={tr(`${appName(row)}の詳細`, `${appName(row)} details`)} disabled={ending} onClick={(event) => { event.stopPropagation(); setSelected(row); }}
                                className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{appName(row)}</button>
                        </th>
                        <td className="whitespace-nowrap px-5 py-3 text-xs text-[var(--studio-text-muted)]">{row.last_used_at ? <time dateTime={row.last_used_at}>{formatDateTime(row.last_used_at, timezone)}</time> : '—'}</td>
                        <td className="px-5 py-3"><StatusPill row={row} /></td>
                    </EditableRow>)}
                </DataTable>
            ) : <div className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <p className="text-sm text-[var(--studio-text-muted)]">{tr('接続している AI アプリはありません。', 'No AI apps are connected.')}</p>
                <ConnectSteps mcpUrl={data?.mcp_url ?? ''} onRefresh={refresh} heading />
            </div>)}
            {showSteps && data && <Overlay title={tr('接続方法', 'How to connect')} help={troubleshooting()} onClose={() => setShowSteps(false)}>
                <ConnectSteps mcpUrl={data.mcp_url} onRefresh={refresh} />
            </Overlay>}
            {selected && <ConnectionDetails row={selected} ending={ending} onEnd={() => void end(selected)} onClose={() => setSelected(null)} />}
        </section>
    );
}

export default function Connections() {
    const { clientId } = useClient();
    // A client switch must not show the previous client's connections.
    return <ConnectionsForClient key={clientId} />;
}
