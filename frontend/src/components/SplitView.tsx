import type { ReactNode } from 'react';

interface SplitViewProps {
    left: ReactNode;
    right: ReactNode;
    leftTitle?: string;
    rightTitle?: string;
}

export default function SplitView({ left, right, leftTitle, rightTitle }: SplitViewProps) {
    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-[calc(100vh-8rem)]">
            {/* Left Pane */}
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden flex flex-col">
                {leftTitle && (
                    <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/50">
                        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">{leftTitle}</h2>
                    </div>
                )}
                <div className="flex-1 overflow-auto p-4">
                    {left}
                </div>
            </div>

            {/* Right Pane */}
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden flex flex-col">
                {rightTitle && (
                    <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/50">
                        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">{rightTitle}</h2>
                    </div>
                )}
                <div className="flex-1 overflow-auto p-4">
                    {right}
                </div>
            </div>
        </div>
    );
}
