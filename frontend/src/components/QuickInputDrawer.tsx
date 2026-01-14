import { useState, useRef, useEffect } from 'react';
import { X, ArrowRightLeft, CreditCard, Sparkles, Loader2, ImagePlus, Send } from 'lucide-react';
import { getAccountsByType, createTransaction, seedDefaultAccounts } from '../api';
import { useToast } from './Toast';

interface QuickInputDrawerProps {
    isOpen: boolean;
    onClose: () => void;
}

const TRANSACTION_TYPES = [
    { value: 'Expense', label: 'Expense', fromType: 'asset', toType: 'expense' },
    { value: 'Income', label: 'Income', fromType: 'income', toType: 'asset' },
    { value: 'Transfer', label: 'Transfer', fromType: 'asset', toType: 'asset' },
    { value: 'Debt Repayment', label: 'Debt Pay', fromType: 'asset', toType: 'liability' },
];

export default function QuickInputDrawer({ isOpen, onClose }: QuickInputDrawerProps) {
    const [activeType, setActiveType] = useState('Expense');
    const [isProcessing, setIsProcessing] = useState(false);
    const [accountsByType, setAccountsByType] = useState<any>({ asset: [], liability: [], income: [], expense: [] });
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { showToast } = useToast();

    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        currency: 'JPY',
        fromAccount: '',
        toAccount: '',
    });

    // AI state
    const [aiInput, setAiInput] = useState('');
    const [selectedImage, setSelectedImage] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            fetchAccounts();
        }
    }, [isOpen]);

    const fetchAccounts = async () => {
        try {
            const data = await getAccountsByType();
            setAccountsByType(data);

            // Set defaults based on type
            const typeConfig = TRANSACTION_TYPES.find(t => t.value === activeType);
            if (typeConfig) {
                const fromAccounts = data[typeConfig.fromType] || [];
                const toAccounts = data[typeConfig.toType] || [];
                setFormData(prev => ({
                    ...prev,
                    fromAccount: fromAccounts[0]?.name || '',
                    toAccount: toAccounts[0]?.name || ''
                }));
            }
        } catch (error) {
            // Seed defaults and retry
            await seedDefaultAccounts();
            const data = await getAccountsByType();
            setAccountsByType(data);
        }
    };

    const currentTypeConfig = TRANSACTION_TYPES.find(t => t.value === activeType);
    const fromAccounts = currentTypeConfig ? accountsByType[currentTypeConfig.fromType] || [] : [];
    const toAccounts = currentTypeConfig ? accountsByType[currentTypeConfig.toType] || [] : [];

    const handleTypeChange = (type: string) => {
        setActiveType(type);
        const typeConfig = TRANSACTION_TYPES.find(t => t.value === type);
        if (typeConfig) {
            const from = accountsByType[typeConfig.fromType] || [];
            const to = accountsByType[typeConfig.toType] || [];
            setFormData(prev => ({
                ...prev,
                fromAccount: from[0]?.name || '',
                toAccount: to[0]?.name || ''
            }));
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!formData.amount || !formData.fromAccount || !formData.toAccount) {
            showToast('Please fill all required fields', 'warning');
            return;
        }

        try {
            await createTransaction({
                date: formData.date,
                description: formData.description || `${activeType} transaction`,
                amount: parseFloat(formData.amount),
                type: (activeType === 'Debt Repayment' ? 'Transfer' : activeType) as 'Income' | 'Expense' | 'Transfer',
                category: formData.toAccount,
                currency: formData.currency,
                from_account: formData.fromAccount,
                to_account: formData.toAccount,
            });

            const symbol = formData.currency === 'JPY' ? '¥' : '$';
            showToast(`Saved: ${activeType === 'Income' ? '+' : '-'}${symbol}${parseFloat(formData.amount).toLocaleString()} from ${formData.fromAccount}`, 'success');

            setFormData(prev => ({ ...prev, description: '', amount: '' }));
            onClose();
        } catch (error) {
            showToast('Failed to save transaction', 'error');
        }
    };

    const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onloadend = () => setSelectedImage(reader.result as string);
            reader.readAsDataURL(file);
        }
    };

    const handleAiParse = async () => {
        if (!aiInput.trim() && !selectedImage) return;

        setIsProcessing(true);
        const apiKey = localStorage.getItem('gemini_api_key');

        if (!apiKey) {
            showToast('Set Gemini API key in Settings', 'warning');
            setIsProcessing(false);
            return;
        }

        try {
            const parts: any[] = [{
                text: `Parse this expense. Return JSON only with: amount (number), currency (JPY/USD), to_account (one of: ${toAccounts.map((a: any) => a.name).join(', ')}), description (string).
Input: "${aiInput || 'Analyze receipt image'}"`
            }];

            if (selectedImage) {
                const base64Data = selectedImage.split(',')[1];
                const mimeType = selectedImage.split(';')[0].split(':')[1];
                parts.push({ inline_data: { mime_type: mimeType, data: base64Data } });
            }

            const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ contents: [{ parts }], generationConfig: { temperature: 0.1 } })
            });

            const data = await response.json();
            const text = data.candidates?.[0]?.content?.parts?.[0]?.text || '';

            const jsonMatch = text.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                const parsed = JSON.parse(jsonMatch[0]);
                setFormData(prev => ({
                    ...prev,
                    amount: String(parsed.amount || ''),
                    currency: parsed.currency || 'JPY',
                    description: parsed.description || '',
                    toAccount: parsed.to_account || prev.toAccount
                }));
                showToast(`Parsed: ¥${parsed.amount} → ${parsed.to_account}`, 'success');
            }
        } catch (error) {
            showToast('AI parsing failed', 'error');
        } finally {
            setIsProcessing(false);
            setAiInput('');
            setSelectedImage(null);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex justify-end">
            <div className="absolute inset-0 bg-black/50" onClick={onClose} />

            <div className="relative w-80 bg-slate-900 border-l border-slate-800 h-full overflow-auto">
                <div className="sticky top-0 bg-slate-900 border-b border-slate-800 px-3 py-2 flex items-center justify-between z-10">
                    <span className="text-xs font-medium">Quick Record</span>
                    <button onClick={onClose} className="p-1 hover:bg-slate-800 text-slate-400">
                        <X size={14} />
                    </button>
                </div>

                <div className="p-3 space-y-3">
                    {/* Type Selector */}
                    <div className="grid grid-cols-4 gap-1">
                        {TRANSACTION_TYPES.map((type) => (
                            <button
                                key={type.value}
                                onClick={() => handleTypeChange(type.value)}
                                className={`py-1.5 text-[10px] transition-colors ${activeType === type.value
                                    ? 'bg-emerald-600 text-white'
                                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                                    }`}
                            >
                                {type.label}
                            </button>
                        ))}
                    </div>

                    {/* AI Quick Parse */}
                    <div className="border border-slate-700 bg-slate-800/30 p-2 space-y-2">
                        <div className="flex items-center gap-1 text-[10px] text-amber-400">
                            <Sparkles size={10} /> AI Parse
                        </div>
                        <div className="flex gap-1">
                            <input
                                type="text"
                                placeholder="e.g., Lunch 1200 yen"
                                value={aiInput}
                                onChange={(e) => setAiInput(e.target.value)}
                                className="flex-1 bg-slate-900 border border-slate-700 px-2 py-1 text-[10px]"
                            />
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                className="px-2 bg-slate-800 border border-slate-700 text-slate-400 hover:text-amber-400"
                            >
                                <ImagePlus size={12} />
                            </button>
                            <button
                                onClick={handleAiParse}
                                disabled={isProcessing || (!aiInput.trim() && !selectedImage)}
                                className="px-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white"
                            >
                                {isProcessing ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                            </button>
                        </div>
                        <input ref={fileInputRef} type="file" accept="image/*" onChange={handleImageSelect} className="hidden" />
                        {selectedImage && (
                            <div className="relative">
                                <img src={selectedImage} alt="Receipt" className="w-full h-16 object-cover" />
                                <button onClick={() => setSelectedImage(null)} className="absolute top-0 right-0 bg-slate-900/80 p-0.5">
                                    <X size={10} />
                                </button>
                            </div>
                        )}
                    </div>

                    {/* Transaction Form */}
                    <form onSubmit={handleSubmit} className="space-y-2">
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-[9px] text-slate-500 uppercase mb-0.5">Date</label>
                                <input
                                    type="date"
                                    value={formData.date}
                                    onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px]"
                                />
                            </div>
                            <div>
                                <label className="block text-[9px] text-slate-500 uppercase mb-0.5">Amount</label>
                                <input
                                    type="number"
                                    placeholder="0"
                                    value={formData.amount}
                                    onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px] font-mono-nums"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-[9px] text-slate-500 uppercase mb-0.5">Description</label>
                            <input
                                type="text"
                                placeholder="What for?"
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px]"
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-[9px] text-slate-500 uppercase mb-0.5">From</label>
                                <select
                                    value={formData.fromAccount}
                                    onChange={(e) => setFormData({ ...formData, fromAccount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px] capitalize"
                                >
                                    {fromAccounts.map((acc: any) => (
                                        <option key={acc.id} value={acc.name}>{acc.name.replace(/_/g, ' ')}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-[9px] text-slate-500 uppercase mb-0.5">To</label>
                                <select
                                    value={formData.toAccount}
                                    onChange={(e) => setFormData({ ...formData, toAccount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px] capitalize"
                                >
                                    {toAccounts.map((acc: any) => (
                                        <option key={acc.id} value={acc.name}>{acc.name.replace(/_/g, ' ')}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <button
                            type="submit"
                            className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium"
                        >
                            <ArrowRightLeft size={12} /> Save
                        </button>
                    </form>

                    {activeType === 'Debt Repayment' && (
                        <div className="flex items-center gap-1 text-[9px] text-slate-500 border-t border-slate-800 pt-2">
                            <CreditCard size={10} /> Paying off liability account
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
