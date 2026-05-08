import type { ReactNode } from 'react';

interface SplitViewProps {
    left: ReactNode;
    right: ReactNode;
    leftTitle?: string;
    rightTitle?: string;
}

export default function SplitView({ left, right, leftTitle, rightTitle }: SplitViewProps) {
    return (
        <div className="grid grid-cols-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] min-[900px]:grid-cols-2 min-[900px]:grid-rows-1 h-full min-h-0">
            {/* Left Pane - Independent scroll */}
            <div className="border-r border-slate-800 flex flex-col h-full min-h-0 overflow-hidden">
                {leftTitle && (
                    <div className="px-3 py-2 border-b border-slate-800 bg-slate-900 flex-shrink-0">
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">{leftTitle}</h2>
                    </div>
                )}
                <div className="flex-1 min-h-0 overflow-hidden p-3">
                    {left}
                </div>
            </div>

            {/* Right Pane - Independent scroll */}
            <div className="flex flex-col h-full min-h-0 overflow-hidden">
                {rightTitle && (
                    <div className="px-3 py-2 border-b border-slate-800 bg-slate-900 flex-shrink-0">
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">{rightTitle}</h2>
                    </div>
                )}
                <div className="flex-1 min-h-0 overflow-hidden p-3">
                    {right}
                </div>
            </div>
        </div>
    );
}
