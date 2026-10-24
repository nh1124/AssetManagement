import { useId, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { isAxiosError } from 'axios';
import { getAiExecutionSettings, getAiOperations, updateAiExecutionSettings, updateAiOperation } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiExecutionSettings, AiMcpWriteMode, AiOperationEntry, AiOperationMode, AiOperationSection, AiOperations } from '../../../types';
import { Help } from '../../components/Help';
import { useConfirm } from '../../components/useConfirm';
import { labels, tr } from '../../i18n';
import { assetErrorMessage, useResource } from '../../useResource';
import { buttonClass, MODE_LABELS } from './labels';
import { effectTag } from './operationRules';

const WRITE_MODES: AiMcpWriteMode[] = ['direct_write', 'change_request'];
const WRITE_MODE_LABELS = labels<AiMcpWriteMode>({
    direct_write: ['直接書き込み', 'Write directly'],
    change_request: ['承認リクエスト経由', 'Through approval requests'],
});
// The chosen permission carries its colour, so a section reads at a glance (WP37).
const MODE_CHECKED: Record<AiOperationMode, string> = {
    allow: 'has-checked:bg-[var(--studio-accent)] has-checked:text-[var(--studio-accent-text)]',
    approval: 'has-checked:bg-[var(--studio-warning)] has-checked:text-white',
    deny: 'has-checked:bg-[var(--studio-danger)] has-checked:text-white',
};
const cardClass = 'rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]';
const pillClass = 'whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium';

const operationName = (operation: Pick<AiOperationEntry, 'ja' | 'en'>) => tr(operation.ja, operation.en);

function Reload({ error, onReload }: { error: string; onReload: () => void }) {
    return <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--studio-danger)]">{error}
        <button type="button" onClick={onReload} className={buttonClass}>{tr('再読み込み', 'Reload')}</button></p>;
}

/** Two named options with a thumb that slides to the chosen one; two radios underneath, so it reads as a choice, not on/off. */
function WriteModeSwitch({ labelledBy, value, disabled, onChoose }: { labelledBy: string; value: AiMcpWriteMode; disabled: boolean; onChoose: (mode: AiMcpWriteMode) => void }) {
    const name = useId();
    return <div role="radiogroup" aria-labelledby={labelledBy} className="relative inline-grid grid-cols-2 rounded-full border border-[var(--studio-border)] bg-[var(--studio-bg)] p-1 text-sm">
        <span aria-hidden="true" className={`absolute inset-y-1 left-1 w-[calc(50%-0.25rem)] rounded-full bg-[var(--studio-accent)] transition-transform duration-200 motion-reduce:transition-none ${value === 'change_request' ? 'translate-x-full' : ''}`} />
        {WRITE_MODES.map((mode) => <label key={mode} className="relative cursor-pointer whitespace-nowrap rounded-full px-4 py-1.5 text-center text-[var(--studio-text-muted)] has-checked:font-medium has-checked:text-[var(--studio-accent-text)] has-focus-visible:ring-2 has-focus-visible:ring-[var(--studio-accent)] has-disabled:cursor-wait has-disabled:opacity-70">
            <input type="radio" name={name} value={mode} checked={value === mode} disabled={disabled} onChange={() => onChoose(mode)} className="sr-only" />
            {WRITE_MODE_LABELS[mode]}
        </label>)}
    </div>;
}

/** The MCP write mode: chosen on the switch, confirmed, then saved at once (owner 2026-10-24, C6'). */
function WriteMode({ settings, onSaved, loading, error, onReload }: {
    settings: AiExecutionSettings | null; onSaved: (settings: AiExecutionSettings) => void;
    loading: boolean; error: string; onReload: () => void;
}) {
    const headingId = useId();
    const confirm = useConfirm();
    const [pending, setPending] = useState<AiMcpWriteMode | null>(null);
    const [operationError, setOperationError] = useState('');
    const choose = async (mode: AiMcpWriteMode) => {
        if (!settings || pending || mode === settings.mcp_write_mode) return;
        setOperationError('');
        const accepted = await confirm(mode === 'change_request'
            ? tr('MCP の書き込み方式を「承認リクエスト経由」に変更します。AI の書き込みは、あなたが承認してから反映されます。', 'Change MCP writes to “Through approval requests”? AI writes are applied after you approve them.')
            : tr('MCP の書き込み方式を「直接書き込み」に変更します。「許可」の操作は、AI がそのまま実行できるようになります。', 'Change MCP writes to “Write directly”? Operations set to “Allow” run as soon as the AI asks.'),
        tr('変更', 'Change'));
        if (!accepted) return;
        setPending(mode);
        try {
            onSaved(await updateAiExecutionSettings({ ...settings, mcp_write_mode: mode }));
        } catch (failure: unknown) {
            setOperationError(assetErrorMessage(failure));
        } finally {
            setPending(null);
        }
    };
    const title = tr('MCP の書き込み方式', 'MCP writes');

    return (
        <section className={`${cardClass} space-y-3 p-5`}>
            <div className="flex flex-wrap items-center justify-between gap-4">
                {/* The switch is named by the title alone, not by the 「?」 text inside the heading. */}
                <h2 className="flex items-center gap-1.5 text-sm font-semibold"><span id={headingId}>{title}</span>
                    <Help label={title} text={tr('直接書き込み：「許可」の操作は AI がそのまま実行します。承認リクエスト経由：AI の書き込みはすべて、あなたが承認してから反映されます。', 'Write directly: operations set to “Allow” run as soon as the AI asks. Through approval requests: every AI write is applied after you approve it.')} wide />
                </h2>
                {settings && !error && <WriteModeSwitch labelledBy={headingId} value={pending ?? settings.mcp_write_mode} disabled={pending !== null} onChoose={(mode) => void choose(mode)} />}
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
            {error && <Reload error={tr(`書き込み方式を取得できませんでした。${error}`, `Could not load the write mode. ${error}`)} onReload={onReload} />}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
        </section>
    );
}

type RowState =
    | { status: 'saving'; mode: AiOperationMode }
    | { status: 'failed'; mode: AiOperationMode; message: string }
    | { status: 'changed_elsewhere' };

/** The mode saved since the screen loaded, when the backend refused a save as changed elsewhere. */
function changedElsewhere(failure: unknown): AiOperationMode | null {
    if (!isAxiosError<{ detail?: { error?: unknown; mode?: unknown } }>(failure) || failure.response?.status !== 409) return null;
    const detail = failure.response.data?.detail;
    return detail?.error === 'changed_elsewhere' && (detail.mode === 'allow' || detail.mode === 'approval' || detail.mode === 'deny') ? detail.mode : null;
}

/** The permission as a row of named options; the chosen one is filled in its colour. */
function PermissionChoice({ name, modes, value, busy, onChoose }: { name: string; modes: AiOperationMode[]; value: AiOperationMode; busy: boolean; onChoose: (mode: AiOperationMode) => void }) {
    const group = useId();
    return <div role="radiogroup" aria-label={tr(`${name}の権限`, `Permission for ${name}`)} aria-busy={busy} className="inline-flex shrink-0 overflow-hidden rounded-md border border-[var(--studio-border)] text-xs">
        {modes.map((mode) => <label key={mode} className={`cursor-pointer border-l border-[var(--studio-border)] px-3 py-1.5 text-[var(--studio-text-muted)] first:border-l-0 hover:bg-[var(--studio-accent-soft)] has-checked:font-medium has-focus-visible:ring-2 has-focus-visible:ring-inset has-focus-visible:ring-[var(--studio-accent)] has-disabled:cursor-wait has-disabled:opacity-60 ${MODE_CHECKED[mode]}`}>
            <input type="radio" name={group} value={mode} checked={value === mode} disabled={busy} onChange={() => onChoose(mode)} className="sr-only" />
            {MODE_LABELS[mode]}
        </label>)}
    </div>;
}

/** How many operations of a section need approval or are denied; nothing else to read in a closed section. */
function SectionSummary({ section }: { section: AiOperationSection }) {
    const approval = section.operations.filter((operation) => operation.mode === 'approval').length;
    const denied = section.operations.filter((operation) => operation.mode === 'deny').length;
    if (!approval && !denied) return <span className="text-xs font-normal text-[var(--studio-text-muted)]">{tr('すべて許可', 'All allowed')}</span>;
    return <span className="flex gap-1.5">
        {approval > 0 && <span className={`${pillClass} border-[var(--studio-warning)] text-[var(--studio-warning)]`}>{tr(`承認 ${approval}`, `Approval ${approval}`)}</span>}
        {denied > 0 && <span className={`${pillClass} border-[var(--studio-danger)] text-[var(--studio-danger)]`}>{tr(`禁止 ${denied}`, `Denied ${denied}`)}</span>}
    </span>;
}

/** Every operation the AI can perform, by section, a permission per row saved on its own (owner 2026-10-24, C7; WP37). */
function Permissions({ data, setData, loading, error, onReload, writeMode }: {
    data: AiOperations | null; setData: (update: (previous: AiOperations | null) => AiOperations | null) => void;
    loading: boolean; error: string; onReload: () => void; writeMode: AiMcpWriteMode | null;
}) {
    const [rows, setRows] = useState<Record<string, RowState>>({});
    // Every way through approval starts with a change request, so denying that closes them all.
    const requests = data?.sections.flatMap((section) => section.operations).find((operation) => operation.key === 'change_requests.create')?.mode !== 'deny';

    const setRow = (key: string, state: RowState | null) => setRows((previous) => {
        const next = { ...previous };
        if (state) next[key] = state; else delete next[key];
        return next;
    });
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
            setRow(operation.key, null);
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
    const title = tr('AI 操作の権限', 'AI operation permissions');

    return (
        <section className="space-y-3">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">{title}
                <Help label={title} text={tr('許可：AI が使えます。承認が必要：AI の変更は、あなたが認証コードで承認してから反映されます。禁止：AI は使えません。あなた自身の操作には効きません。', 'Allow: the AI can use it. Needs approval: the AI’s change is applied after you approve it with your authenticator code. Deny: the AI cannot use it. Your own actions are not affected.')} wide />
            </h2>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('読み込んでいます…', 'Loading…')}</p>}
            {error && <Reload error={tr(`操作の一覧を取得できませんでした。${error}`, `Could not load the operations. ${error}`)} onReload={onReload} />}
            {data && !error && <div className={`${cardClass} divide-y divide-[var(--studio-border)] overflow-hidden`}>{data.sections.map((section) => <details key={section.key} className="group">
                <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-3 text-sm font-medium hover:bg-[var(--studio-accent-soft)] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--studio-accent)] [&::-webkit-details-marker]:hidden">
                    <ChevronDown size={16} aria-hidden="true" className="shrink-0 -rotate-90 text-[var(--studio-text-muted)] transition-transform group-open:rotate-0 motion-reduce:transition-none" />
                    <span className="flex-1">{tr(section.ja, section.en)}</span>
                    <SectionSummary section={section} />
                </summary>
                <ul className="divide-y divide-[var(--studio-border)] border-t border-[var(--studio-border)] bg-[var(--studio-bg)]">
                    {section.operations.map((operation) => {
                        const state = rows[operation.key];
                        const name = operationName(operation);
                        const tag = writeMode ? effectTag(operation, operation.mode, writeMode, requests) : null;
                        return <li key={operation.key} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 pl-12 pr-5">
                            <span className={`flex items-center gap-2 text-sm ${tag === 'unavailable' ? 'text-[var(--studio-text-muted)]' : ''}`}>{name}
                                {tag === 'via_approval' && <span className={`${pillClass} border-[var(--studio-warning)] text-[var(--studio-warning)]`}>{tr('承認経由', 'Via approval')}</span>}
                                {tag === 'unavailable' && <span className={`${pillClass} border-[var(--studio-border-strong)] text-[var(--studio-text-muted)]`}>{tr('使えない', 'Unavailable')}</span>}
                            </span>
                            <PermissionChoice name={name} modes={operation.modes} value={state?.status === 'saving' ? state.mode : operation.mode} busy={state?.status === 'saving'} onChoose={(mode) => void save(operation, mode)} />
                            {state?.status === 'failed' && <p role="alert" className="flex basis-full flex-wrap items-center justify-end gap-2 text-xs text-[var(--studio-danger)]">{tr(`保存できませんでした（${state.message}）`, `Could not save (${state.message})`)}
                                <button type="button" onClick={() => void save(operation, state.mode)} className={buttonClass}>{tr('再試行', 'Retry')}</button></p>}
                            {state?.status === 'changed_elsewhere' && <p role="alert" className="basis-full text-right text-xs text-[var(--studio-warning)]">{tr('別の画面で変更されていました。今の値を表示しています。', 'It was changed elsewhere. Showing the current value.')}</p>}
                        </li>;
                    })}
                </ul>
            </details>)}</div>}
        </section>
    );
}

function AiForClient() {
    const operations = useResource(getAiOperations);
    const settings = useResource(getAiExecutionSettings);
    return <div className="space-y-6">
        <WriteMode settings={settings.data} onSaved={settings.setData} loading={settings.loading} error={settings.error} onReload={settings.reload} />
        <Permissions data={operations.data} setData={operations.setData} loading={operations.loading} error={operations.error} onReload={operations.reload}
            writeMode={settings.data && !settings.error ? settings.data.mcp_write_mode : null} />
    </div>;
}

export default function Ai() {
    const { clientId } = useClient();
    // A client switch must discard responses and row states from the previous client.
    return <AiForClient key={clientId} />;
}
