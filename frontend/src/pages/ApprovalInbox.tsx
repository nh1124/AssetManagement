import { useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    CheckCircle2,
    Clock,
    Filter,
    Play,
    RefreshCw,
    RotateCw,
    ShieldCheck,
    XCircle,
} from 'lucide-react';
import {
    applyAiChangeRequest,
    approveAiChangeRequest,
    getAiChangeRequests,
    reauth,
    refreshAiChangeRequestPreview,
    rejectAiChangeRequest,
} from '../api';
import AiDiffViewer from '../components/AiDiffViewer';
import { useToast } from '../components/Toast';
import type { AiChangeRequest, AiChangeRequestStatus } from '../types';

type StatusFilter = 'pending' | 'approved' | 'failed' | 'expired' | 'applied' | 'rejected' | 'all';

const statusTabs: Array<{ id: StatusFilter; label: string }> = [
    { id: 'pending', label: 'Pending' },
    { id: 'approved', label: 'Approved' },
    { id: 'failed', label: 'Failed' },
    { id: 'expired', label: 'Expired' },
    { id: 'applied', label: 'Applied' },
    { id: 'rejected', label: 'Rejected' },
    { id: 'all', label: 'All' },
];

const statusTone: Record<AiChangeRequestStatus, string> = {
    draft: 'border-slate-600 text-slate-300',
    pending: 'border-amber-500/50 text-amber-300',
    approved: 'border-cyan-500/50 text-cyan-300',
    applied: 'border-emerald-500/50 text-emerald-300',
    rejected: 'border-slate-600 text-slate-400',
    expired: 'border-orange-500/50 text-orange-300',
    failed: 'border-rose-500/50 text-rose-300',
};

const riskTone: Record<string, string> = {
    low: 'text-slate-300',
    medium: 'text-cyan-300',
    high: 'text-amber-300',
    critical: 'text-rose-300',
};

const dateText = (value?: string | null) => value ? new Date(value).toLocaleString() : '-';
const titleText = (change: AiChangeRequest) => `${change.resource}:${change.action}`;

export default function ApprovalInboxPage() {
    const { showToast } = useToast();
    const [status, setStatus] = useState<StatusFilter>('pending');
    const [items, setItems] = useState<AiChangeRequest[]>([]);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [busyAction, setBusyAction] = useState<string | null>(null);
    const [stepPassword, setStepPassword] = useState('');
    const [stepCode, setStepCode] = useState('');
    const [stepRecoveryCode, setStepRecoveryCode] = useState('');

    const selected = useMemo(
        () => items.find((item) => item.id === selectedId) || items[0] || null,
        [items, selectedId],
    );

    useEffect(() => {
        loadRequests();
    }, [status]);

    useEffect(() => {
        if (items.length && !items.some((item) => item.id === selectedId)) {
            setSelectedId(items[0].id);
        }
    }, [items, selectedId]);

    const loadRequests = async () => {
        setIsLoading(true);
        try {
            const data = await getAiChangeRequests({ status: status === 'all' ? undefined : status, limit: 100 });
            setItems(data);
        } catch (error: any) {
            showToast(error.response?.data?.detail || 'Failed to load approval inbox', 'error');
        } finally {
            setIsLoading(false);
        }
    };

    const replaceItem = (next: AiChangeRequest) => {
        setItems((prev) => prev.map((item) => item.id === next.id ? next : item));
        setSelectedId(next.id);
    };

    const runAction = async (label: string, action: () => Promise<AiChangeRequest>, toast: string) => {
        setBusyAction(label);
        try {
            const next = await action();
            replaceItem(next);
            showToast(toast, 'success');
            await loadRequests();
        } catch (error: any) {
            const detail = error.response?.data?.detail;
            showToast(typeof detail === 'string' ? detail : error.message || 'Approval action failed', 'error');
        } finally {
            setBusyAction(null);
        }
    };

    const approveSelected = async () => {
        if (!selected) return;
        const needsStepUp = selected.requires_mfa || selected.risk === 'critical';
        await runAction(
            'approve',
            async () => {
                if (!needsStepUp) return approveAiChangeRequest(selected.id);
                const step = await reauth({
                    current_password: stepPassword || undefined,
                    code: stepCode || undefined,
                    recovery_code: stepRecoveryCode || undefined,
                });
                setStepPassword('');
                setStepCode('');
                setStepRecoveryCode('');
                return approveAiChangeRequest(selected.id, { step_up_token: step.step_up_token });
            },
            'Change request approved',
        );
    };

    const canApprove = selected?.status === 'pending';
    const canApply = selected?.status === 'approved';
    const canReject = selected?.status === 'pending' || selected?.status === 'approved';
    const needsStepUp = Boolean(selected && (selected.requires_mfa || selected.risk === 'critical') && canApprove);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden p-2">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border border-slate-800 bg-slate-900/70 px-3 py-2">
                <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                        <ShieldCheck size={17} className="text-emerald-300" />
                        Approval Inbox
                    </div>
                    <p className="mt-1 text-[10px] uppercase tracking-wide text-slate-500">
                        AI-generated changes awaiting human control
                    </p>
                </div>
                <button
                    type="button"
                    onClick={loadRequests}
                    disabled={isLoading}
                    className="flex items-center gap-2 border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:border-emerald-500 hover:text-emerald-300 disabled:opacity-50"
                >
                    <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
                    Refresh
                </button>
            </div>

            <div className="mb-2 flex gap-1 overflow-x-auto border border-slate-800 bg-slate-950/40 p-1 scrollbar-subtle">
                {statusTabs.map((tab) => (
                    <button
                        key={tab.id}
                        type="button"
                        onClick={() => setStatus(tab.id)}
                        className={`flex shrink-0 items-center gap-1 border px-3 py-1.5 text-xs transition-colors ${status === tab.id
                            ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300'
                            : 'border-transparent text-slate-500 hover:text-slate-200'
                        }`}
                    >
                        <Filter size={12} />
                        {tab.label}
                    </button>
                ))}
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden lg:grid-cols-[360px_minmax(0,1fr)]">
                <section className="min-h-0 overflow-y-auto border border-slate-800 bg-slate-900/60 scrollbar-subtle">
                    {isLoading && items.length === 0 ? (
                        <div className="flex h-48 items-center justify-center text-xs text-slate-500">Loading...</div>
                    ) : items.length === 0 ? (
                        <div className="flex h-48 items-center justify-center text-xs text-slate-500">No change requests.</div>
                    ) : (
                        <div className="divide-y divide-slate-800">
                            {items.map((item) => {
                                const isActive = selected?.id === item.id;
                                return (
                                    <button
                                        key={item.id}
                                        type="button"
                                        onClick={() => setSelectedId(item.id)}
                                        className={`block w-full px-3 py-3 text-left transition-colors ${isActive ? 'bg-slate-800/80' : 'hover:bg-slate-800/40'}`}
                                    >
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="min-w-0">
                                                <p className="truncate text-sm font-medium text-slate-100">{titleText(item)}</p>
                                                <p className="mt-1 truncate text-[10px] text-slate-500">
                                                    {item.tool_name || item.source} / {dateText(item.created_at)}
                                                </p>
                                            </div>
                                            <span className={`shrink-0 border px-2 py-0.5 text-[10px] ${statusTone[item.status]}`}>
                                                {item.status}
                                            </span>
                                        </div>
                                        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
                                            <span className={riskTone[item.risk]}>{item.risk}</span>
                                            <span className="text-slate-600">changes {Number(item.diff?.count ?? 0)}</span>
                                            {item.requires_mfa && <span className="text-amber-300">MFA</span>}
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </section>

                <section className="min-h-0 overflow-y-auto border border-slate-800 bg-slate-900/60 p-3 scrollbar-subtle">
                    {!selected ? (
                        <div className="flex h-full min-h-80 items-center justify-center text-xs text-slate-500">
                            Select a change request.
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 pb-3">
                                <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <h2 className="truncate text-lg font-semibold text-slate-50">{titleText(selected)}</h2>
                                        <span className={`border px-2 py-0.5 text-[10px] ${statusTone[selected.status]}`}>{selected.status}</span>
                                        <span className={`text-xs ${riskTone[selected.risk]}`}>{selected.risk}</span>
                                    </div>
                                    <p className="mt-1 text-xs text-slate-500">
                                        {selected.source} / {selected.tool_name || 'no tool'} / {dateText(selected.created_at)}
                                    </p>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <button
                                        type="button"
                                        onClick={() => runAction('refresh', () => refreshAiChangeRequestPreview(selected.id), 'Preview refreshed')}
                                        disabled={Boolean(busyAction)}
                                        className="flex items-center gap-2 border border-slate-700 px-3 py-2 text-xs hover:border-cyan-500 hover:text-cyan-300 disabled:opacity-50"
                                    >
                                        <RotateCw size={14} />
                                        Preview
                                    </button>
                                    <button
                                        type="button"
                                        onClick={approveSelected}
                                        disabled={!canApprove || Boolean(busyAction) || (needsStepUp && !stepPassword && !stepCode && !stepRecoveryCode)}
                                        className="flex items-center gap-2 border border-emerald-500/50 px-3 py-2 text-xs text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"
                                    >
                                        <CheckCircle2 size={14} />
                                        Approve
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => runAction('apply', () => applyAiChangeRequest(selected.id), 'Change request applied')}
                                        disabled={!canApply || Boolean(busyAction)}
                                        className="flex items-center gap-2 border border-cyan-500/50 px-3 py-2 text-xs text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50"
                                    >
                                        <Play size={14} />
                                        Apply
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => runAction('reject', () => rejectAiChangeRequest(selected.id), 'Change request rejected')}
                                        disabled={!canReject || Boolean(busyAction)}
                                        className="flex items-center gap-2 border border-rose-500/50 px-3 py-2 text-xs text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                                    >
                                        <XCircle size={14} />
                                        Reject
                                    </button>
                                </div>
                            </div>

                            {needsStepUp && (
                                <div className="border border-amber-500/30 bg-amber-950/10 p-3">
                                    <div className="mb-2 flex items-center gap-2 text-xs font-medium text-amber-200">
                                        <AlertTriangle size={14} />
                                        Step-up required before approval
                                    </div>
                                    <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                                        <input
                                            type="password"
                                            value={stepPassword}
                                            onChange={(event) => setStepPassword(event.target.value)}
                                            placeholder="Current password"
                                            className="border border-slate-700 bg-slate-950 px-3 py-2 text-xs outline-none focus:border-amber-500"
                                        />
                                        <input
                                            type="text"
                                            value={stepCode}
                                            onChange={(event) => setStepCode(event.target.value)}
                                            placeholder="Authenticator code"
                                            className="border border-slate-700 bg-slate-950 px-3 py-2 text-xs outline-none focus:border-amber-500"
                                        />
                                        <input
                                            type="text"
                                            value={stepRecoveryCode}
                                            onChange={(event) => setStepRecoveryCode(event.target.value)}
                                            placeholder="Recovery code"
                                            className="border border-slate-700 bg-slate-950 px-3 py-2 text-xs outline-none focus:border-amber-500"
                                        />
                                    </div>
                                </div>
                            )}

                            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                                <Meta label="ID" value={String(selected.id)} />
                                <Meta label="Target" value={Object.entries(selected.target_ref || {}).map(([key, value]) => `${key}:${String(value)}`).join(' / ') || '-'} />
                                <Meta label="Precondition" value={selected.precondition_hash || '-'} />
                                <Meta label="Expires" value={dateText(selected.expires_at)} />
                            </div>

                            <AiDiffViewer change={selected} />

                            {selected.status === 'failed' && (
                                <pre className="max-h-52 overflow-auto border border-rose-500/30 bg-rose-950/10 p-2 text-[10px] leading-5 text-rose-100 scrollbar-subtle">
                                    {JSON.stringify(selected.result, null, 2)}
                                </pre>
                            )}

                            <div className="flex items-center gap-2 text-[10px] text-slate-600">
                                <Clock size={12} />
                                Updated {dateText(selected.updated_at)}
                            </div>
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
}

function Meta({ label, value }: { label: string; value: string }) {
    return (
        <div className="min-w-0 border border-slate-800 bg-slate-950/50 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
            <div className="mt-1 truncate text-xs text-slate-200" title={value}>{value}</div>
        </div>
    );
}
