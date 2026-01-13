import type { ReactNode } from 'react';

interface SplitViewProps {
    left: ReactNode;
    right: ReactNode;
    leftTitle?: string;
    rightTitle?: string;
}

export default function SplitView({ left, right, leftTitle, rightTitle }: SplitViewProps) {
    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 h-[calc(100vh-7rem)] border border-slate-800">
            {/* Left Pane */}
            <div className="border-r border-slate-800 overflow-hidden flex flex-col bg-slate-900/50">
                {leftTitle && (
                    <div className="px-3 py-2 border-b border-slate-800 bg-slate-900">
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">{leftTitle}</h2>
                    </div>
                )}
                <div className="flex-1 overflow-auto p-3">
                    {left}
                </div>
            </div>

            {/* Right Pane */}
            <div className="overflow-hidden flex flex-col bg-slate-900/50">
                {rightTitle && (
                    <div className="px-3 py-2 border-b border-slate-800 bg-slate-900">
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">{rightTitle}</h2>
                    </div>
                )}
                <div className="flex-1 overflow-auto p-3">
                    {right}
                </div>
            </div>
        </div>
    );
}
