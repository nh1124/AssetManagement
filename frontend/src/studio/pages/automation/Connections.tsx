import { useState } from 'react';
import { endMcpConnection, getMcpConnections } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { McpConnection } from '../../../types';
import Overlay from '../../components/Overlay';
import { Help } from '../../components/Help';
import { useConfirm } from '../../components/useConfirm';
import { formatDate, formatDateTime, useTimezone } from '../../datetime';
import { tr } from '../../i18n';
import { assetErrorMessage, useResource } from '../../useResource';
import { buttonClass } from './labels';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);
const cellClass = 'block px-5 py-1 md:table-cell md:py-3';

function appName(row: McpConnection) {
    return row.client_name || row.oauth_client_id;
}

/** On narrow screens a row stands as labelled lines, so 切断 never leaves the screen. */
function CellLabel({ children }: { children: string }) {
    return <span aria-hidden="true" className="block text-xs text-[var(--studio-text-muted)] md:hidden">{children}</span>;
}

type Copied = { target: 'command' | 'url'; ok: boolean } | null;

function CopyButton({ text, target, label, copied, onCopied }: { text: string; target: 'command' | 'url'; label: string; copied: Copied; onCopied: (copied: Copied) => void }) {
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(text);
            onCopied({ target, ok: true });
        } catch { onCopied({ target, ok: false }); }
    };
    return <span className="inline-flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => void copy()} disabled={!text} className={buttonClass}>{label}</button>
        {copied?.target === target && <span role={copied.ok ? 'status' : 'alert'} className="text-xs">{copied.ok ? tr('コピーしました。', 'Copied.') : tr('コピーできません。選んでコピーしてください。', 'Could not copy. Select the text and copy it.')}</span>}
    </span>;
}

/** How to connect an AI app, in three steps: shown in the overlay, and in place of the table while nothing is connected. */
function ConnectSteps({ mcpUrl, onRefresh }: { mcpUrl: string; onRefresh: () => void }) {
    const [copied, setCopied] = useState<Copied>(null);
    const command = mcpUrl ? `claude mcp add --transport http --scope user asset-management ${mcpUrl}` : '';
    const title = tr('接続の手順', 'How to connect');
    return <div className="space-y-3 text-sm">
        <p className="flex items-center gap-1.5 font-semibold">{title}
            <Help label={title} text={tr('繋がらないときは、アプリが表示するエラーを確認してください（invalid_client：アプリの登録が見つからない、invalid_redirect_uri：戻り先が登録と違う、invalid_target：別のサーバー宛て）。', 'If it does not connect, check the error the app shows (invalid_client: the app’s registration was not found; invalid_redirect_uri: the return address differs from the registration; invalid_target: meant for another server).')} wide />
        </p>
        <ol className="list-decimal space-y-4 pl-5">
            <li className="space-y-2"><p className="font-medium">{tr('接続先を登録する', 'Add the server')}</p>
                {mcpUrl ? <>
                    <p className="text-xs text-[var(--studio-text-muted)]">{tr('使うアプリに合わせて、どちらかで登録します。', 'Use whichever fits your app.')}</p>
                    <div className="space-y-1"><p>{tr('Claude Code：ターミナルで次のコマンドを実行します。', 'Claude Code: run this command in a terminal.')}</p>
                        <code className="block select-all break-all font-mono text-xs">{command}</code>
                        <CopyButton text={command} target="command" label={tr('コマンドをコピー', 'Copy the command')} copied={copied} onCopied={setCopied} /></div>
                    <div className="space-y-1"><p>{tr('ほかのアプリ：この URL を「リモート MCP サーバー」や「コネクタ」として登録します。', 'Other apps: add this URL as a remote MCP server or connector.')}</p>
                        <code className="block select-all break-all font-mono text-xs">{mcpUrl}</code>
                        <CopyButton text={mcpUrl} target="url" label={tr('URL をコピー', 'Copy the URL')} copied={copied} onCopied={setCopied} /></div>
                </> : <p role="alert" className="text-[var(--studio-danger)]">{tr('接続先の URL が設定されていません。', 'The server URL is not set.')}</p>}
            </li>
            <li className="space-y-1"><p className="font-medium">{tr('ログインして許可する', 'Sign in and allow')}</p>
                <p>{tr('アプリが開くログイン画面で、この画面にサインインするときのユーザー名・パスワード・認証コードを入れて許可します。', 'On the sign-in page the app opens, enter the username, password and authenticator code you sign in here with, and allow it.')}</p></li>
            <li className="space-y-2"><p className="font-medium">{tr('接続を確かめる', 'Check the connection')}</p>
                <p>{tr('この画面に戻って一覧を更新し、アプリが表に出ることを確かめます。', 'Come back here, refresh the list and check the app appears in it.')}</p>
                <button type="button" onClick={onRefresh} className={buttonClass}>{tr('一覧を更新', 'Refresh the list')}</button></li>
        </ol>
    </div>;
}

/** The AI apps this person connected over MCP, how to connect one, and ending a connection (WP35, own page since WP36). */
function ConnectionsForClient() {
    const { data, setData, loading, error, reload } = useResource(getMcpConnections);
    const confirm = useConfirm();
    const timezone = useTimezone();
    const [showSteps, setShowSteps] = useState(false);
    const [ending, setEnding] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const refresh = () => {
        setShowSteps(false);
        setOperationError('');
        setConfirmation('');
        reload();
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
    const listTitle = tr('AIアプリの接続', 'AI app connections');
    const statusTitle = tr('状態・期限', 'Status and expiry');

    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="flex items-center gap-1.5 text-sm text-[var(--studio-text-muted)]">{tr('MCP で繋いだ AI アプリの一覧です。', 'The AI apps connected over MCP.')}
                    <Help label={listTitle} text={tr('接続は、AI アプリ（Claude Code など）のログイン画面であなたがユーザー名・パスワード・認証コードを入れて許可したときにできます。切断すると、そのアプリは次の操作から使えなくなります。', 'A connection is made when you allow an AI app (such as Claude Code) on its sign-in page with your username, password and authenticator code. A disconnected app stops working from its next operation.')} wide />
                </p>
                <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={refresh} disabled={loading || ending !== null} className={buttonClass}>{tr('一覧を更新', 'Refresh the list')}</button>
                    <button type="button" aria-haspopup="dialog" onClick={() => setShowSteps(true)} disabled={!data} className={buttonClass}>{tr('接続方法の確認', 'How to connect')}</button>
                </div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('接続の一覧を取得できませんでした。', 'Could not load the connections. ')}{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && !loading && !error && (data.connections.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="block w-full text-left text-sm md:table">
                        <thead className="hidden border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)] md:table-header-group"><tr>
                            {[tr('アプリ', 'App'), tr('接続情報', 'Connection'), tr('接続日時・最終利用', 'Connected · last used')].map((label) => <th key={label} scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{label}</th>)}
                            <th scope="col" className="whitespace-nowrap px-5 py-3 font-medium"><span className="inline-flex items-center gap-1.5">{statusTitle}
                                <Help label={statusTitle} text={tr('有効：このアプリは今使えます。期限は使うと延びるものがあります。再接続が必要：パスワードの変更や全端末からのサインアウトの後で、使うにはもう一度接続（ログイン）が要ります。', 'Active: the app works now; some expiry dates extend when the app is used. Reconnect required: after a password change or a sign-out everywhere, the app has to connect (sign in) again.')} end wide /></span></th>
                            <th scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{tr('操作', 'Action')}</th>
                        </tr></thead>
                        <tbody className="block divide-y divide-[var(--studio-border)] md:table-row-group">
                            {data.connections.map((row) => <tr key={row.id} className="block py-2 md:table-row md:py-0">
                                <th scope="row" className={`${cellClass} font-medium`}>{appName(row)}<span className="mt-1 block break-all text-xs font-normal text-[var(--studio-text-muted)]">{row.oauth_client_id}</span></th>
                                <td className={cellClass}><CellLabel>{tr('接続情報', 'Connection')}</CellLabel>
                                    {row.client_source === 'cimd'
                                        ? tr(`公開された情報（${row.client_host ?? ''}）`, `Published by ${row.client_host ?? ''}`)
                                        : tr('このサーバーに登録したアプリ', 'Registered with this server')}
                                    <span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{tr('戻り先：', 'Returns to: ')}{row.redirect_host && LOOPBACK_HOSTS.has(row.redirect_host)
                                        ? tr(`このコンピューター（${row.redirect_host}）`, `this computer (${row.redirect_host})`)
                                        : row.redirect_host ?? '—'}</span></td>
                                <td className={`${cellClass} text-xs`}><CellLabel>{tr('接続日時・最終利用', 'Connected · last used')}</CellLabel>
                                    <span className="block whitespace-nowrap">{tr('接続：', 'Connected: ')}<time dateTime={row.connected_at}>{formatDateTime(row.connected_at, timezone)}</time></span>
                                    <span className="block whitespace-nowrap text-[var(--studio-text-muted)]">{tr('最終利用：', 'Last used: ')}{row.last_used_at ? <time dateTime={row.last_used_at}>{formatDateTime(row.last_used_at, timezone)}</time> : '—'}</span></td>
                                <td className={cellClass}><CellLabel>{statusTitle}</CellLabel>
                                    {row.status === 'active' ? tr('有効', 'Active') : <span className="text-[var(--studio-danger)]">{tr('再接続が必要', 'Reconnect required')}</span>}
                                    <span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{row.refreshable
                                        ? tr(`${formatDate(row.expires_at, timezone)}まで（使うと延長）`, `Until ${formatDate(row.expires_at, timezone)} (extended when used)`)
                                        : tr(`${formatDateTime(row.expires_at, timezone)}まで`, `Until ${formatDateTime(row.expires_at, timezone)}`)}</span></td>
                                <td className={`${cellClass} pb-3`}><button type="button" onClick={() => void end(row)} disabled={ending !== null} aria-label={tr(`「${appName(row)}」を切断`, `Disconnect “${appName(row)}”`)} className={buttonClass}>{ending === row.id ? tr('切断中…', 'Disconnecting…') : tr('切断', 'Disconnect')}</button></td>
                            </tr>)}
                        </tbody>
                    </table>
                </div>
            ) : <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <p className="text-sm">{tr('接続しているAIアプリはありません。', 'No AI apps are connected.')}</p>
                <ConnectSteps mcpUrl={data.mcp_url} onRefresh={refresh} />
            </div>)}
            {showSteps && data && <Overlay title={tr('接続方法の確認', 'How to connect')} onClose={() => setShowSteps(false)}>
                <ConnectSteps mcpUrl={data.mcp_url} onRefresh={refresh} />
            </Overlay>}
        </section>
    );
}

export default function Connections() {
    const { clientId } = useClient();
    // A client switch must not show the previous client's connections.
    return <ConnectionsForClient key={clientId} />;
}
