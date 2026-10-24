import { useId, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { isAxiosError } from 'axios';
import { getAiExecutionSettings, getAiOperations, updateAiExecutionSettings, updateAiOperation } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiExecutionSettings, AiMcpWriteMode, AiOperationEntry, AiOperationMode, AiOperations } from '../../../types';
import { Help } from '../../components/Help';
import { useConfirm } from '../../components/useConfirm';
import { labels, tr } from '../../i18n';
import { assetErrorMessage, useResource } from '../../useResource';
import { buttonClass, inputClass, MODE_LABELS, RISK_LABELS } from './labels';
import { operationEffect, operationMatches, type KindFilter, type OperationEffect } from './operationRules';

const WRITE_MODES: AiMcpWriteMode[] = ['direct_write', 'change_request'];
const WRITE_MODE_LABELS = labels<AiMcpWriteMode>({
    direct_write: ['直接書き込み', 'Write directly'],
    change_request: ['承認リクエスト経由', 'Through approval requests'],
});
const KIND_FILTERS: KindFilter[] = ['all', 'read', 'write'];
const KIND_LABELS = labels<KindFilter>({ all: ['すべて', 'All'], read: ['読み取り', 'Reads'], write: ['書き込み', 'Writes'] });
const EFFECT_LABELS = labels<OperationEffect>({
    read: ['読み取れる', 'Can read'],
    no_read: ['読み取れない', 'Cannot read'],
    direct: ['直接実行できる', 'Runs directly'],
    available: ['使える（書き込み方式に関係なく）', 'Available in either write mode'],
    through_approval: ['承認リクエストで実行（人が承認）', 'Through an approval request (a person approves)'],
    not_in_mode: ['この方式では使えない', 'Not available in this write mode'],
    no_requests: ['使えない（承認リクエストの作成が禁止）', 'Not available (creating approval requests is denied)'],
    denied: ['使えない', 'Not available'],
});
const UNAVAILABLE: OperationEffect[] = ['no_read', 'not_in_mode', 'no_requests', 'denied'];
const cellClass = 'block px-5 py-1 md:table-cell md:py-3 md:align-top';

const operationName = (operation: Pick<AiOperationEntry, 'ja' | 'en'>) => tr(operation.ja, operation.en);

/** On narrow screens a row stands as labelled lines: name, permission, what it means now. */
function CellLabel({ children }: { children: string }) {
    return <span aria-hidden="true" className="block text-xs text-[var(--studio-text-muted)] md:hidden">{children}</span>;
}

function Reload({ error, onReload }: { error: string; onReload: () => void }) {
    return <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--studio-danger)]">{error}
        <button type="button" onClick={onReload} className={buttonClass}>{tr('再読み込み', 'Reload')}</button></p>;
}

/** Two named options with a thumb that slides to the chosen one; two radios underneath, so it reads as a choice, not on/off. */
function WriteModeSwitch({ labelledBy, value, disabled, onChoose }: { labelledBy: string; value: AiMcpWriteMode; disabled: boolean; onChoose: (mode: AiMcpWriteMode) => void }) {
    const name = useId();
    return <div role="radiogroup" aria-labelledby={labelledBy} className="relative inline-grid grid-cols-2 rounded-full border border-[var(--studio-border)] bg-[var(--studio-bg)] p-1 text-sm">
        <span aria-hidden="true" className={`absolute inset-y-1 left-1 w-[calc(50%-0.25rem)] rounded-full bg-[var(--studio-accent)] transition-transform duration-200 motion-reduce:transition-none ${value === 'change_request' ? 'translate-x-full' : ''}`} />
        {WRITE_MODES.map((mode) => <label key={mode} className="relative cursor-pointer whitespace-nowrap rounded-full px-4 py-1.5 text-center text-[var(--studio-text-muted)] has-checked:font-medium has-checked:text-[var(--studio-accent-text)] has-focus-visible:ring-2 has-focus-visible:ring-[var(--studio-accent)] has-disabled:cursor-not-allowed has-disabled:opacity-70">
            <input type="radio" name={name} value={mode} checked={value === mode} disabled={disabled} onChange={() => onChoose(mode)} className="sr-only" />
            {WRITE_MODE_LABELS[mode]}
        </label>)}
    </div>;
}

/** The MCP write mode: chosen on the switch, confirmed, then saved at once (owner 2026-10-24, C6'). */
function WriteMode({ settings, onSaved, loading, error, onReload, approvalNames }: {
    settings: AiExecutionSettings | null; onSaved: (settings: AiExecutionSettings) => void;
    loading: boolean; error: string; onReload: () => void; approvalNames: string[];
}) {
    const headingId = useId();
    const confirm = useConfirm();
    const [pending, setPending] = useState<AiMcpWriteMode | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const choose = async (mode: AiMcpWriteMode) => {
        if (!settings || pending || mode === settings.mcp_write_mode) return;
        setOperationError('');
        setConfirmation('');
        const accepted = await confirm(mode === 'change_request'
            ? tr('MCP の書き込み方式を「承認リクエスト経由」に変更します。AI の直接の書き込みは使えなくなり、承認リクエストに対応する操作だけが、人の承認の後に反映されます。', 'Change MCP writes to “Through approval requests”? The AI can no longer write directly; only operations an approval request supports go through, after a person approves.')
            : tr('MCP の書き込み方式を「直接書き込み」に変更します。権限が「許可」の書き込みは、AI がそのまま実行できるようになります。', 'Change MCP writes to “Write directly”? Writes whose permission is “Allow” run as soon as the AI asks.'),
        tr('変更', 'Change'));
        if (!accepted) return;
        setPending(mode);
        try {
            onSaved(await updateAiExecutionSettings({ ...settings, mcp_write_mode: mode }));
            setConfirmation(tr(`MCP の書き込み方式を「${WRITE_MODE_LABELS[mode]}」にしました。`, `MCP writes are now “${WRITE_MODE_LABELS[mode]}”.`));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            setPending(null);
        }
    };
    const title = tr('MCP の書き込み方式', 'MCP writes');
    const approvalList = approvalNames.length ? approvalNames.join(tr('・', ', ')) : tr('（一覧を読み込めていません）', '(the list has not loaded)');

    return (
        <section className="space-y-3">
            {/* The switch is named by the title alone, not by the 「?」 text inside the heading. */}
            <h2 className="flex items-center gap-1.5 text-lg font-semibold"><span id={headingId}>{title}</span>
                <Help label={title} text={tr(`直接書き込み：権限が「許可」の書き込みを AI がそのまま実行します。「承認が必要」の操作は、AI が承認リクエストを作り、人が承認してから反映されます。承認リクエスト経由：AI の書き込みはすべて承認リクエストになります。承認リクエストに対応する操作は ${approvalList} です。`, `Write directly: writes whose permission is “Allow” run as soon as the AI asks; operations that need approval go through an approval request a person approves. Through approval requests: every AI write becomes an approval request. The operations an approval request supports: ${approvalList}.`)} wide />
            </h2>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
            {error && <Reload error={tr(`書き込み方式を取得できませんでした。${error}`, `Could not load the write mode. ${error}`)} onReload={onReload} />}
            {settings && !error && <>
                <WriteModeSwitch labelledBy={headingId} value={pending ?? settings.mcp_write_mode} disabled={pending !== null} onChoose={(mode) => void choose(mode)} />
                {pending && <p role="status" className="text-xs text-[var(--studio-text-muted)]">{tr('保存中…', 'Saving…')}</p>}
                {!pending && settings.mcp_write_mode === 'change_request' && <p className="text-xs text-[var(--studio-text-muted)]">{tr('承認リクエスト経由では、承認リクエストに対応していない書き込みは使えません。', 'Through approval requests, writes an approval request does not support are not available.')}</p>}
            </>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
        </section>
    );
}

type RowState =
    | { status: 'saving'; mode: AiOperationMode }
    | { status: 'saved' }
    | { status: 'failed'; mode: AiOperationMode; message: string }
    | { status: 'changed_elsewhere' };

/** The mode saved since the screen loaded, when the backend refused a save as changed elsewhere. */
function changedElsewhere(failure: unknown): AiOperationMode | null {
    if (!isAxiosError<{ detail?: { error?: unknown; mode?: unknown } }>(failure) || failure.response?.status !== 409) return null;
    const detail = failure.response.data?.detail;
    return detail?.error === 'changed_elsewhere' && (detail.mode === 'allow' || detail.mode === 'approval' || detail.mode === 'deny') ? detail.mode : null;
}

function RowStatus({ state, onRetry }: { state: RowState | undefined; onRetry: () => void }) {
    if (!state) return null;
    if (state.status === 'saving') return <span role="status" className="block text-xs text-[var(--studio-text-muted)]">{tr('保存中…', 'Saving…')}</span>;
    if (state.status === 'saved') return <span role="status" className="block text-xs text-[var(--studio-positive)]">{tr('保存しました', 'Saved')}</span>;
    if (state.status === 'changed_elsewhere') return <span role="alert" className="block text-xs text-[var(--studio-warning)]">{tr('別の画面で変更されていました。今の値を表示しています。', 'It was changed elsewhere. Showing the current value.')}</span>;
    return <span role="alert" className="flex flex-wrap items-center gap-2 text-xs text-[var(--studio-danger)]">{tr(`保存できませんでした（${state.message}）`, `Could not save (${state.message})`)}
        <button type="button" onClick={onRetry} className={buttonClass}>{tr('再試行', 'Retry')}</button></span>;
}

/** Every operation the AI can perform, a permission per row, each saved on its own (owner 2026-10-24, C7). */
function Permissions({ data, setData, loading, error, onReload, writeMode }: {
    data: AiOperations | null; setData: (update: (previous: AiOperations | null) => AiOperations | null) => void;
    loading: boolean; error: string; onReload: () => void; writeMode: AiMcpWriteMode | null;
}) {
    const [query, setQuery] = useState('');
    const [kind, setKind] = useState<KindFilter>('all');
    const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
    const [rows, setRows] = useState<Record<string, RowState>>({});
    const filterName = useId();
    const searching = query.trim() !== '';
    const all = data?.sections.flatMap((section) => section.operations) ?? [];
    // Every way through approval starts with a change request, so denying that closes them all.
    const requests = all.find((operation) => operation.key === 'change_requests.create')?.mode !== 'deny';
    const sections = data?.sections
        .map((section) => ({ ...section, shown: section.operations.filter((operation) => operationMatches(operation, query, kind)) }))
        .filter((section) => section.shown.length) ?? [];
    const localTools = kind === 'write' ? [] : data?.local_tools.filter((tool) => operationMatches({ kind: 'read', key: tool, ja: '', en: '', tools: [] }, query, 'all')) ?? [];

    const setRow = (key: string, state: RowState) => setRows((previous) => ({ ...previous, [key]: state }));
    const replace = (updated: AiOperationEntry) => setData((previous) => previous && {
        ...previous,
        sections: previous.sections.map((section) => ({
            ...section, operations: section.operations.map((operation) => operation.key === updated.key ? updated : operation),
        })),
    });
    const save = async (operation: AiOperationEntry, mode: AiOperationMode) => {
        if (rows[operation.key]?.status === 'saving') return;
        setRow(operation.key, { status: 'saving', mode });
        try {
            replace(await updateAiOperation(operation.key, { mode, expected_mode: operation.mode }));
            setRow(operation.key, { status: 'saved' });
        } catch (failure: unknown) {
            const current = changedElsewhere(failure);
            if (current) {
                replace({ ...operation, mode: current, saved: true });
                setRow(operation.key, { status: 'changed_elsewhere' });
            } else {
                setRow(operation.key, { status: 'failed', mode, message: assetErrorMessage(failure) });
            }
        }
    };
    const toggle = (key: string) => setCollapsed((previous) => {
        const next = new Set(previous);
        if (!next.delete(key)) next.add(key);
        return next;
    });
    const title = tr('AI 操作の権限', 'AI operation permissions');

    return (
        <section className="space-y-4">
            <h2 className="flex items-center gap-1.5 text-lg font-semibold">{title}
                <Help label={title} text={tr('MCP で繋いだ AI アプリが使える操作の一覧です。権限は行ごとに選ぶとすぐ保存されます。許可：AI が使える。承認が必要：AI は承認リクエストを作り、人が認証コードを入れて承認してから反映される。禁止：AI は使えない。あなた自身の画面の操作には効きません。', 'Every operation an AI app connected over MCP can use. A permission is saved as soon as you choose it. Allow: the AI can use it. Needs approval: the AI creates an approval request, applied after a person approves it with an authenticator code. Deny: the AI cannot use it. Your own actions on these screens are not affected.')} wide />
            </h2>
            <div className="flex flex-wrap items-center gap-3">
                <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label={tr('操作を検索', 'Search operations')} placeholder={tr('操作名・ツール名で検索', 'Search by operation or tool')} className={`w-64 max-w-full ${inputClass}`} />
                <div role="radiogroup" aria-label={tr('種類で絞り込む', 'Filter by kind')} className="flex gap-2">
                    {KIND_FILTERS.map((value) => <label key={value} className="cursor-pointer rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] has-checked:border-[var(--studio-accent)] has-checked:bg-[var(--studio-accent-soft)] has-checked:text-[var(--studio-accent)] has-focus-visible:ring-2 has-focus-visible:ring-[var(--studio-accent)]">
                        <input type="radio" name={filterName} value={value} checked={kind === value} onChange={() => setKind(value)} className="sr-only" />{KIND_LABELS[value]}
                    </label>)}
                </div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
            {error && <Reload error={tr(`操作の一覧を取得できませんでした。${error}`, `Could not load the operations. ${error}`)} onReload={onReload} />}
            {data && !error && (sections.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="block w-full text-left text-sm md:table">
                        <thead className="hidden border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)] md:table-header-group"><tr>
                            {[tr('操作', 'Operation'), tr('権限', 'Permission'), tr('今の扱い', 'What it means now')].map((label) => <th key={label} scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{label}</th>)}
                        </tr></thead>
                        {sections.map((section) => {
                            const open = searching || !collapsed.has(section.key);
                            const denied = section.operations.filter((operation) => operation.mode === 'deny').length;
                            const bodyId = `${filterName}-${section.key}`;
                            return <tbody key={section.key} id={bodyId} className="block border-t border-[var(--studio-border)] first-of-type:border-t-0 md:table-row-group">
                                <tr className="block md:table-row"><th scope="rowgroup" colSpan={3} className="block bg-[var(--studio-bg)] px-3 py-2 md:table-cell">
                                    <button type="button" aria-expanded={open} aria-controls={bodyId} disabled={searching} onClick={() => toggle(section.key)} className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm font-semibold hover:bg-[var(--studio-accent-soft)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:cursor-default disabled:hover:bg-transparent">
                                        <ChevronDown size={16} aria-hidden="true" className={`shrink-0 transition-transform motion-reduce:transition-none ${open ? '' : '-rotate-90'}`} />
                                        {tr(section.ja, section.en)}
                                        <span className="text-xs font-normal text-[var(--studio-text-muted)]">{tr(`${section.operations.length} 操作・禁止 ${denied}`, `${section.operations.length} operations · ${denied} denied`)}{(searching || kind !== 'all') && tr(`・表示 ${section.shown.length}`, ` · ${section.shown.length} shown`)}</span>
                                    </button>
                                </th></tr>
                                {open && section.shown.map((operation) => {
                                    const state = rows[operation.key];
                                    const shownMode = state?.status === 'saving' ? state.mode : operation.mode;
                                    const effect = writeMode ? operationEffect(operation, operation.mode, writeMode, requests) : null;
                                    const name = operationName(operation);
                                    return <tr key={operation.key} className="block py-2 md:table-row md:py-0">
                                        <th scope="row" className={`${cellClass} font-medium`}>{name}
                                            <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{operation.kind === 'read' ? tr('読み取り', 'Read') : tr('書き込み', 'Write')}{tr('・リスク：', ' · Risk: ')}{RISK_LABELS[operation.risk]}</span>
                                            <span className="mt-1 block break-all font-mono text-[11px] font-normal text-[var(--studio-text-muted)]">{operation.tools.length ? operation.tools.join(' · ') : tr('（MCP のツールなし）', '(no MCP tool)')}</span>
                                        </th>
                                        <td className={cellClass}><CellLabel>{tr('権限', 'Permission')}</CellLabel>
                                            <select aria-label={tr(`${name}の権限`, `Permission for ${name}`)} value={shownMode} disabled={state?.status === 'saving'} onChange={(event) => void save(operation, event.target.value as AiOperationMode)} className={inputClass}>
                                                {operation.modes.map((mode) => <option key={mode} value={mode}>{MODE_LABELS[mode]}</option>)}
                                            </select>
                                            <RowStatus state={state} onRetry={() => { if (state?.status === 'failed') void save(operation, state.mode); }} />
                                        </td>
                                        <td className={`${cellClass} pb-3`}><CellLabel>{tr('今の扱い', 'What it means now')}</CellLabel>
                                            {effect ? <span className={UNAVAILABLE.includes(effect) ? 'text-[var(--studio-text-muted)]' : ''}>{EFFECT_LABELS[effect]}</span> : '—'}
                                        </td>
                                    </tr>;
                                })}
                            </tbody>;
                        })}
                    </table>
                </div>
            ) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 text-sm text-[var(--studio-text-muted)]">{tr('一致する操作はありません。', 'No operations match.')}</p>)}
            {data && !error && localTools.length > 0 && <p className="text-xs text-[var(--studio-text-muted)]">
                <span className="font-medium">{tr('計算だけのツール（データを使わないので権限の対象外）：', 'Tools that only compute (they use no data, so no permission applies): ')}</span>
                <span className="break-all font-mono">{localTools.join(' · ')}</span>
            </p>}
        </section>
    );
}

function AiForClient() {
    const operations = useResource(getAiOperations);
    const settings = useResource(getAiExecutionSettings);
    const approvalNames = operations.data?.sections.flatMap((section) => section.operations).filter((operation) => operation.approval).map(operationName) ?? [];
    return <div className="space-y-8">
        <WriteMode settings={settings.data} onSaved={settings.setData} loading={settings.loading} error={settings.error} onReload={settings.reload} approvalNames={approvalNames} />
        <Permissions data={operations.data} setData={operations.setData} loading={operations.loading} error={operations.error} onReload={operations.reload}
            writeMode={settings.data && !settings.error ? settings.data.mcp_write_mode : null} />
    </div>;
}

export default function Ai() {
    const { clientId } = useClient();
    // A client switch must discard responses and row states from the previous client.
    return <AiForClient key={clientId} />;
}
