import { Gift, Info } from 'lucide-react';
import type { QuickTemplate } from '../../types';
import { quickKindLabel, quickPresetFor, type LanguageCode } from './quick';

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
    const Icon = preset?.icon || Gift;
    const infoText = preset?.description[language] || template.description || quickKindLabel(template.template_kind);

    return (
        <button
            type="button"
            onClick={() => onSelect(template)}
            className={`relative min-h-20 border px-3 py-2 text-center transition-colors ${selected ? 'border-emerald-500 bg-emerald-950/30' : 'border-slate-700 bg-slate-800/50 hover:border-slate-500'}`}
            title={infoText}
        >
            <span className="absolute right-1.5 top-1.5 text-slate-500 hover:text-emerald-300" title={infoText}>
                <Info size={11} />
            </span>
            <Icon size={24} className={`mx-auto mb-1 ${preset?.color || 'text-emerald-400'}`} />
            <span className="block text-xs font-bold text-white truncate">{template.name}</span>
            <span className="block text-[10px] text-slate-500 truncate">{quickKindLabel(template.template_kind)}</span>
        </button>
    );
}
