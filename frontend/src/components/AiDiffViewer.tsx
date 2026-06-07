import { ChevronDown, FileJson, GitCompareArrows } from 'lucide-react';
import type { AiChangeRequest } from '../types';

interface AiDiffViewerProps {
    change: Pick<AiChangeRequest, 'diff' | 'before_snapshot' | 'after_snapshot' | 'validation'>;
    compact?: boolean;
}

type DiffChange = {
    field: string;
    before: unknown;
    after: unknown;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

const diffChanges = (diff: Record<string, unknown>): DiffChange[] => {
    const changes = diff.changes;
    if (!Array.isArray(changes)) return [];
    return changes
        .filter(isRecord)
        .map((item) => ({
            field: String(item.field ?? ''),
            before: item.before,
            after: item.after,
        }))
        .filter((item) => item.field);
};

const valueText = (value: unknown): string => {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return JSON.stringify(value);
};

const validationMessages = (validation: Record<string, unknown>): string[] => {
    const direct = validation.messages;
    if (Array.isArray(direct)) return direct.map(String);
    const warnings = Array.isArray(validation.warnings) ? validation.warnings.map(String) : [];
    const errors = Array.isArray(validation.errors) ? validation.errors.map(String) : [];
    return [...errors, ...warnings];
};

export default function AiDiffViewer({ change, compact = false }: AiDiffViewerProps) {
    const changes = diffChanges(change.diff);
    const messages = validationMessages(change.validation);

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-200">
                    <GitCompareArrows size={15} className="text-cyan-300" />
                    <span>{changes.length} field changes</span>
                </div>
                {messages.length > 0 && (
                    <span className="border border-amber-500/40 px-2 py-0.5 text-[10px] text-amber-300">
                        {messages.length} validation notes
                    </span>
                )}
            </div>

            {messages.length > 0 && (
                <div className="border border-amber-500/30 bg-amber-950/10 p-2">
                    {messages.map((message, index) => (
                        <p key={`${message}-${index}`} className="text-xs leading-5 text-amber-200">
                            {message}
                        </p>
                    ))}
                </div>
            )}

            {changes.length === 0 ? (
                <div className="border border-slate-800 bg-slate-950/50 px-3 py-6 text-center text-xs text-slate-500">
                    No material field changes.
                </div>
            ) : (
                <div className="overflow-hidden border border-slate-800">
                    <div className="grid grid-cols-[minmax(120px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)] border-b border-slate-800 bg-slate-950/70 px-2 py-1.5 text-[10px] uppercase tracking-wide text-slate-500">
                        <span>Field</span>
                        <span>Before</span>
                        <span>After</span>
                    </div>
                    <div className={compact ? 'max-h-64 overflow-y-auto scrollbar-subtle' : 'max-h-[34rem] overflow-y-auto scrollbar-subtle'}>
                        {changes.map((item) => (
                            <div
                                key={item.field}
                                className="grid grid-cols-[minmax(120px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)] border-b border-slate-800/70 px-2 py-2 text-xs last:border-b-0"
                            >
                                <div className="truncate font-medium text-slate-300" title={item.field}>{item.field}</div>
                                <div className="min-w-0 break-words pr-2 font-mono text-[11px] leading-5 text-slate-500">{valueText(item.before)}</div>
                                <div className="min-w-0 break-words font-mono text-[11px] leading-5 text-emerald-200">{valueText(item.after)}</div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {!compact && (
                <details className="border border-slate-800 bg-slate-950/40">
                    <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-xs text-slate-400">
                        <span className="flex items-center gap-2"><FileJson size={14} /> Snapshot detail</span>
                        <ChevronDown size={14} />
                    </summary>
                    <div className="grid grid-cols-1 gap-2 border-t border-slate-800 p-2 lg:grid-cols-2">
                        <pre className="max-h-72 overflow-auto border border-slate-800 bg-slate-950 p-2 text-[10px] leading-5 text-slate-500 scrollbar-subtle">
                            {JSON.stringify(change.before_snapshot, null, 2)}
                        </pre>
                        <pre className="max-h-72 overflow-auto border border-slate-800 bg-slate-950 p-2 text-[10px] leading-5 text-slate-300 scrollbar-subtle">
                            {JSON.stringify(change.after_snapshot, null, 2)}
                        </pre>
                    </div>
                </details>
            )}
        </div>
    );
}
