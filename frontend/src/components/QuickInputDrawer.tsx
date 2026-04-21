import { useState, useRef, useEffect } from 'react';
import { X, ArrowRightLeft, CreditCard, Sparkles, Loader2, ImagePlus, Send } from 'lucide-react';
import { getAccountsByType, createTransaction, seedDefaultAccounts, analyzeWithBackend } from '../api';
import { useToast } from './Toast';

interface QuickInputDrawerProps {
    isOpen: boolean;
    onClose: () => void;
}

type TransactionKind = 'Expense' | 'Income' | 'Transfer' | 'LiabilityPayment';
type AccountGroup = 'asset' | 'liability' | 'income' | 'expense';

interface AccountOption {
    id: number;
    name: string;
}

const TRANSACTION_TYPES: Array<{
    value: TransactionKind;
    label: string;
    fromType: AccountGroup;
    toType: AccountGroup;
}> = [
    { value: 'Expense', label: 'Expense', fromType: 'asset', toType: 'expense' },
    { value: 'Income', label: 'Income', fromType: 'income', toType: 'asset' },
    { value: 'Transfer', label: 'Transfer', fromType: 'asset', toType: 'asset' },
    { value: 'LiabilityPayment', label: 'Debt Pay', fromType: 'asset', toType: 'liability' },
];

const EMPTY_ACCOUNTS: Record<AccountGroup, AccountOption[]> = {
    asset: [],
    liability: [],
    income: [],
    expense: [],
};

function normalizeAccountsByType(raw: unknown): Record<AccountGroup, AccountOption[]> {
    const data = (raw ?? {}) as Record<string, Array<{ id: number; name: string }>>;
    return {
        asset: data.asset ?? [],
        liability: data.liability ?? [],
        income: data.income ?? [],
        expense: data.expense ?? [],
    };
}

export default function QuickInputDrawer({ isOpen, onClose }: QuickInputDrawerProps) {
    const [activeType, setActiveType] = useState<TransactionKind>('Expense');
    const [isProcessing, setIsProcessing] = useState(false);
    const [accountsByType, setAccountsByType] = useState<Record<AccountGroup, AccountOption[]>>(EMPTY_ACCOUNTS);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { showToast } = useToast();

    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        currency: 'JPY',
        fromAccountId: '',
        toAccountId: '',
    });

    const [aiInput, setAiInput] = useState('');
    const [selectedImage, setSelectedImage] = useState<string | null>(null);

    const currentTypeConfig = TRANSACTION_TYPES.find((t) => t.value === activeType) ?? TRANSACTION_TYPES[0];
    const fromAccounts = accountsByType[currentTypeConfig.fromType] ?? [];
    const toAccounts = accountsByType[currentTypeConfig.toType] ?? [];

    const resetAccountSelection = (type: TransactionKind, groupedAccounts: Record<AccountGroup, AccountOption[]>) => {
        const typeConfig = TRANSACTION_TYPES.find((t) => t.value === type) ?? TRANSACTION_TYPES[0];
        const from = groupedAccounts[typeConfig.fromType] ?? [];
        const to = groupedAccounts[typeConfig.toType] ?? [];

        setFormData((prev) => ({
            ...prev,
            fromAccountId: from[0] ? String(from[0].id) : '',
            toAccountId: to[0] ? String(to[0].id) : '',
        }));
    };

    const fetchAccounts = async () => {
        try {
            const response = await getAccountsByType();
            const normalized = normalizeAccountsByType(response);
            setAccountsByType(normalized);
            resetAccountSelection(activeType, normalized);
        } catch {
            await seedDefaultAccounts();
            const response = await getAccountsByType();
            const normalized = normalizeAccountsByType(response);
            setAccountsByType(normalized);
            resetAccountSelection(activeType, normalized);
        }
    };

    useEffect(() => {
        if (isOpen) {
            fetchAccounts();
        }
    }, [isOpen]);

    const handleTypeChange = (type: TransactionKind) => {
        setActiveType(type);
        resetAccountSelection(type, accountsByType);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!formData.amount || !formData.fromAccountId || !formData.toAccountId) {
            showToast('Please fill all required fields', 'warning');
            return;
        }

        const fromAccountId = parseInt(formData.fromAccountId, 10);
        const toAccountId = parseInt(formData.toAccountId, 10);
        const fromAccount = fromAccounts.find((acc) => acc.id === fromAccountId);
        const toAccount = toAccounts.find((acc) => acc.id === toAccountId);

        try {
            await createTransaction({
                date: formData.date,
                description: formData.description || `${activeType} transaction`,
                amount: parseFloat(formData.amount),
                type: activeType,
                category: toAccount?.name || '',
                currency: formData.currency,
                from_account_id: fromAccountId,
                to_account_id: toAccountId,
            });

            showToast(
                `Saved: ${activeType === 'Income' ? '+' : '-'} ${formData.currency} ${parseFloat(formData.amount).toLocaleString()} from ${fromAccount?.name ?? 'account'}`,
                'success'
            );

            setFormData((prev) => ({ ...prev, description: '', amount: '' }));
            onClose();
        } catch {
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

        try {
            const parts: any[] = [{
                text: `Parse this expense. Return JSON only with: amount (number), currency (JPY/USD), to_account (one of: ${toAccounts.map((a) => a.name).join(', ')}), description (string).\nInput: "${aiInput || 'Analyze receipt image'}"`
            }];

            if (selectedImage) {
                const base64Data = selectedImage.split(',')[1];
                const mimeType = selectedImage.split(';')[0].split(':')[1];
                parts.push({
                    inline_data: {
                        mime_type: mimeType,
                        data: base64Data,
                    },
                });
            }

            const data = await analyzeWithBackend({ parts });
            const text = data.candidates?.[0]?.content?.parts?.[0]?.text || '';

            const jsonMatch = text.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                const parsed = JSON.parse(jsonMatch[0]) as {
                    amount?: number;
                    currency?: string;
                    description?: string;
                    to_account?: string;
                };

                const parsedToAccount = toAccounts.find(
                    (acc) => acc.name.toLowerCase() === String(parsed.to_account || '').toLowerCase()
                );

                setFormData((prev) => ({
                    ...prev,
                    amount: String(parsed.amount ?? ''),
                    currency: parsed.currency || 'JPY',
                    description: parsed.description || '',
                    toAccountId: parsedToAccount ? String(parsedToAccount.id) : prev.toAccountId,
                }));

                showToast(`Parsed: ${parsed.currency || 'JPY'} ${parsed.amount ?? ''}`, 'success');
            }
        } catch (error: any) {
            const detail = error.response?.data?.detail || 'AI parsing failed';
            showToast(detail, 'error');
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
                                    value={formData.fromAccountId}
                                    onChange={(e) => setFormData({ ...formData, fromAccountId: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px] capitalize"
                                >
                                    <option value="">Select...</option>
                                    {fromAccounts.map((acc) => (
                                        <option key={acc.id} value={acc.id}>{acc.name.replace(/_/g, ' ')}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-[9px] text-slate-500 uppercase mb-0.5">To</label>
                                <select
                                    value={formData.toAccountId}
                                    onChange={(e) => setFormData({ ...formData, toAccountId: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1 text-[10px] capitalize"
                                >
                                    <option value="">Select...</option>
                                    {toAccounts.map((acc) => (
                                        <option key={acc.id} value={acc.id}>{acc.name.replace(/_/g, ' ')}</option>
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

                    {activeType === 'LiabilityPayment' && (
                        <div className="flex items-center gap-1 text-[9px] text-slate-500 border-t border-slate-800 pt-2">
                            <CreditCard size={10} /> Paying off liability account
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

