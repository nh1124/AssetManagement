import type { ReactNode } from 'react';

interface MobilePlaceholderProps {
    title: string;
    children?: ReactNode;
}

export default function MobilePlaceholder({ title, children }: MobilePlaceholderProps) {
    return (
        <div className="p-4">
            <section className="border border-slate-800 bg-slate-900/70 p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Mobile workspace</p>
                <h1 className="mt-2 text-lg font-semibold text-slate-100">{title}</h1>
                <div className="mt-3 text-sm leading-6 text-slate-400">
                    {children ?? 'This mobile screen is intentionally separated from the desktop UI and will be built as a focused workflow.'}
                </div>
            </section>
        </div>
    );
}
