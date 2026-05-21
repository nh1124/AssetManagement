import { ArrowRightLeft, ChevronRight } from 'lucide-react';
import type { QuickTemplate } from '../../types';
import { quickKindLabelFor, quickPresetFor, quickTemplateDisplay, type LanguageCode } from './quick';

type QuickTemplateTileProps = {
    template: QuickTemplate;
    language: LanguageCode;
    selected: boolean;
    onSelect: (template: QuickTemplate) => void;
};

export default function QuickTemplateTile({
    template,
    language,
    selected,
    onSelect,
}: QuickTemplateTileProps) {
    const preset = quickPresetFor(template);
    const Icon = preset?.icon || ArrowRightLeft;
    const display = quickTemplateDisplay(template, language);
    const infoText = preset?.description[language] || display.description;

    return (
        <button
            type="button"
            onClick={() => onSelect(template)}
            className={`h-28 w-28 rounded-2xl border p-3 text-left transition-colors ${selected ? 'border-emerald-500 bg-emerald-950/30' : 'border-slate-800 bg-slate-900/70 hover:border-slate-600 hover:bg-slate-900'}`}
            title={infoText}
        >
            <div className="flex items-start justify-between gap-2">
                <Icon size={19} className={preset?.color || 'text-emerald-300'} />
                <ChevronRight size={15} className="text-slate-600" />
            </div>
            <span className="mt-3 block truncate text-sm font-medium text-slate-100">{display.name}</span>
            <span className="mt-1 block truncate text-[10px] text-slate-500">{display.tray} - {quickKindLabelFor(template.template_kind, language)}</span>
        </button>
    );
}
