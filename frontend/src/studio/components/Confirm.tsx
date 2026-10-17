import { useId, type ReactNode } from 'react';
import Overlay from './Overlay';

export default function Confirm({ title, children, confirmLabel, onConfirm, onCancel }: {
    title: string; children: ReactNode; confirmLabel: string;
    onConfirm: () => void; onCancel: () => void;
}) {
    const bodyId = useId();
    const danger = /削除|破棄/.test(confirmLabel);
    return <Overlay title={title} describedBy={bodyId} onClose={onCancel} footer={<>
        <button autoFocus type="button" onClick={onCancel} className="rounded-md border border-[var(--studio-border)] px-3 py-2 text-sm text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)]">キャンセル</button>
        <button type="button" onClick={onConfirm} className={`rounded-md px-4 py-2 text-sm font-medium hover:opacity-90 ${danger ? 'bg-[var(--studio-danger)] text-white' : 'bg-[var(--studio-accent)] text-[var(--studio-accent-text)]'}`}>{confirmLabel}</button>
    </>}><div id={bodyId} className="whitespace-pre-wrap text-sm leading-relaxed">{children}</div></Overlay>;
}
