import type { ReactNode } from 'react';

interface Tab {
    id: string;
    label: string;
}

interface TabPanelProps {
    tabs: Tab[];
    activeTab: string;
    onTabChange: (tabId: string) => void;
    children: ReactNode;
}

export default function TabPanel({ tabs, activeTab, onTabChange, children }: TabPanelProps) {
    return (
        <div className="flex flex-col h-full">
            {/* Tab Bar */}
            <div className="flex border-b border-slate-800 bg-slate-900/80">
                {tabs.map((tab) => (
                    <button
                        key={tab.id}
                        onClick={() => onTabChange(tab.id)}
                        className={`px-4 py-2 text-xs font-medium transition-colors ${activeTab === tab.id
                                ? 'tab-active bg-slate-800/50'
                                : 'tab-inactive hover:bg-slate-800/30'
                            }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-auto p-3">
                {children}
            </div>
        </div>
    );
}
