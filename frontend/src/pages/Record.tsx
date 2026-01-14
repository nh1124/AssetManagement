import { useState, useEffect, useRef } from 'react';
import { Plus, ArrowUpCircle, ArrowDownCircle, RefreshCw, Edit, Trash2, Sparkles, Send, Loader2, ImagePlus, X } from 'lucide-react';
import SplitView from '../components/SplitView';
import TabPanel from '../components/TabPanel';
import type { Transaction } from '../types';
import { getTransactions, createTransaction } from '../api';

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

const INPUT_TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'ai', label: 'AI' },
];

export default function RecordPage() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [activeTab, setActiveTab] = useState('transaction');
    const [isProcessing, setIsProcessing] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as 'Income' | 'Expense' | 'Transfer' | 'Debt',
        category: '',
        currency: 'JPY',
        fromAccount: '',
        toAccount: '',
    });

    // AI state
    const [aiInput, setAiInput] = useState('');
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const [suggestedTransactions, setSuggestedTransactions] = useState<any[]>([]);

    useEffect(() => {
        getTransactions().then(setTransactions).catch(console.error);
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const newTransaction = await createTransaction({
                date: formData.date,
                description: formData.description,
                amount: parseFloat(formData.amount),
                type: formData.type,
                category: formData.category,
                currency: formData.currency,
                from_account: formData.fromAccount,
                to_account: formData.toAccount,
            });
            setTransactions([newTransaction, ...transactions]);
            setFormData({ ...formData, description: '', amount: '', category: '' });
        } catch (error) {
            console.error('Failed to create transaction:', error);
        }
    };

    const handleConfirmSuggestions = async () => {
        setIsProcessing(true);
        try {
            const savedTransactions = [];
            for (const suggestion of suggestedTransactions) {
                const newTx = await createTransaction({
                    date: suggestion.date || formData.date,
                    description: suggestion.description,
                    amount: suggestion.amount,
                    type: suggestion.type as any || 'Expense',
                    category: suggestion.category || '',
                    currency: suggestion.currency || 'JPY',
                    from_account: suggestion.from_account || 'cash',
                    to_account: suggestion.to_account || 'expense',
                });
                savedTransactions.push(newTx);
            }
            setTransactions([...savedTransactions, ...transactions]);
            setSuggestedTransactions([]);
            setAiInput('');
            setSelectedImage(null);
            setActiveTab('transaction');
        } catch (error) {
            console.error('Failed to confirm suggestions:', error);
        } finally {
            setIsProcessing(false);
        }
    };

    const removeSuggestion = (index: number) => {
        setSuggestedTransactions(suggestedTransactions.filter((_, i) => i !== index));
    };

    const getCurrencySymbol = (currency: string) => {
        const symbols: Record<string, string> = { JPY: '¥', USD: '$', EUR: '€', GBP: '£', CNY: '¥' };
        return symbols[currency] || currency;
    };

    const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onloadend = () => {
                setSelectedImage(reader.result as string);
            };
            reader.readAsDataURL(file);
        }
    };

    const handleAiSubmit = async () => {
        if (!aiInput.trim() && !selectedImage) return;

        setIsProcessing(true);
        setSuggestedTransactions([]);

        try {
            const parts: any[] = [];
            if (aiInput) parts.push({ text: aiInput });

            if (selectedImage) {
                const base64Data = selectedImage.split(',')[1];
                const mimeType = selectedImage.split(';')[0].split(':')[1];
                parts.push({
                    inline_data: { mime_type: mimeType, data: base64Data }
                });
            }

            const importApi = await import('../api');
            const results = await importApi.analyzeWithBackend({ parts });

            if (Array.isArray(results)) {
                setSuggestedTransactions(results);
            }
        } catch (error) {
            console.error('AI Processing error:', error);
        } finally {
            setIsProcessing(false);
        }
    };

    const leftPane = (
        <TabPanel tabs={INPUT_TABS} activeTab={activeTab} onTabChange={setActiveTab}>
            {activeTab === 'transaction' && (
                <form onSubmit={handleSubmit} className="space-y-3">
                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                            <input
                                type="date"
                                value={formData.date}
                                onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Type</label>
                            <select
                                value={formData.type}
                                onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="Expense">Expense</option>
                                <option value="Income">Income</option>
                                <option value="Transfer">Transfer</option>
                                <option value="Debt">Debt Repayment</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description</label>
                        <input
                            type="text"
                            placeholder="What was this for?"
                            value={formData.description}
                            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                            <input
                                type="number"
                                placeholder="0"
                                value={formData.amount}
                                onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Currency</label>
                            <select
                                value={formData.currency}
                                onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                {CURRENCIES.map((c) => (
                                    <option key={c} value={c}>{c}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                            <select
                                value={formData.fromAccount}
                                onChange={(e) => setFormData({ ...formData, fromAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select...</option>
                                <option value="cash">Cash</option>
                                <option value="bank">Bank Account</option>
                                <option value="credit">Credit Card</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To Account</label>
                            <select
                                value={formData.toAccount}
                                onChange={(e) => setFormData({ ...formData, toAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select...</option>
                                <option value="expense">Expense</option>
                                <option value="savings">Savings</option>
                                <option value="investment">Investment</option>
                            </select>
                        </div>
                    </div>

                    <button
                        type="submit"
                        className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                    >
                        <Plus size={14} /> Save Transaction
                    </button>
                </form>
            )}

            {activeTab === 'ai' && (
                <div className="space-y-4">
                    <div className="border border-amber-800/50 bg-amber-900/10 p-2 text-xs">
                        <p className="flex items-center gap-1 text-amber-400">
                            <Sparkles size={12} /> Extract multiple records from text or images
                        </p>
                    </div>

                    {!suggestedTransactions.length ? (
                        <>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description or instruction</label>
                                <textarea
                                    placeholder="e.g., Spent 1500 yen on lunch and 2000 yen on a movie today"
                                    value={aiInput}
                                    onChange={(e) => setAiInput(e.target.value)}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500 h-24 resize-none"
                                />
                            </div>

                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Receipt / Document Image</label>
                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={() => fileInputRef.current?.click()}
                                        className="flex-1 bg-slate-800 border border-dashed border-slate-600 hover:border-amber-500 py-3 flex items-center justify-center gap-1 text-xs text-slate-400 hover:text-amber-400"
                                    >
                                        <ImagePlus size={16} /> {selectedImage ? 'Change Image' : 'Upload Image'}
                                    </button>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        accept="image/*"
                                        onChange={handleImageSelect}
                                        className="hidden"
                                    />
                                </div>
                            </div>

                            {selectedImage && (
                                <div className="relative">
                                    <img src={selectedImage} alt="Receipt" className="w-full h-32 object-cover border border-slate-700" />
                                    <button
                                        onClick={() => setSelectedImage(null)}
                                        className="absolute top-1 right-1 bg-slate-900/80 p-1 text-slate-400 hover:text-white"
                                    >
                                        <X size={14} />
                                    </button>
                                </div>
                            )}

                            <button
                                onClick={handleAiSubmit}
                                disabled={isProcessing || (!aiInput.trim() && !selectedImage)}
                                className="w-full bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white py-2.5 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                            >
                                {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                                {isProcessing ? 'Thinking...' : 'Extract Records'}
                            </button>
                        </>
                    ) : (
                        <div className="space-y-3 animate-in fade-in slide-in-from-bottom-2">
                            <div className="flex items-center justify-between">
                                <h3 className="text-[10px] text-amber-500 font-bold uppercase tracking-widest">Suggested Records</h3>
                                <button
                                    onClick={() => setSuggestedTransactions([])}
                                    className="text-[10px] text-slate-500 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                            </div>

                            <div className="space-y-2 max-h-[400px] overflow-auto pr-1">
                                {suggestedTransactions.map((st, idx) => (
                                    <div key={idx} className="bg-slate-800/50 border border-slate-700 p-3 relative group">
                                        <div className="flex justify-between items-start mb-2">
                                            <div>
                                                <p className="text-xs font-medium text-white">{st.description}</p>
                                                <p className="text-[10px] text-slate-500">{st.date} • {st.category}</p>
                                            </div>
                                            <p className="text-xs font-mono font-bold text-amber-400">
                                                {getCurrencySymbol(st.currency)}{st.amount.toLocaleString()}
                                            </p>
                                        </div>
                                        <button
                                            onClick={() => removeSuggestion(idx)}
                                            className="absolute -top-2 -right-2 bg-rose-500 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                                        >
                                            <X size={10} />
                                        </button>
                                    </div>
                                ))}
                            </div>

                            <button
                                onClick={handleConfirmSuggestions}
                                disabled={isProcessing}
                                className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 flex items-center justify-center gap-2 text-xs font-bold transition-all active:scale-[0.98]"
                            >
                                {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                Confirm & Save All ({suggestedTransactions.length})
                            </button>
                        </div>
                    )}
                </div>
            )}
        </TabPanel>
    );

    const rightPane = (
        <div className="space-y-3">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Recent Transactions</h3>
            <div className="space-y-0.5 max-h-[calc(100vh-180px)] overflow-auto">
                {transactions.length === 0 ? (
                    <p className="text-slate-600 text-xs py-8 text-center">No transactions yet</p>
                ) : (
                    transactions.map((tx) => (
                        <div
                            key={tx.id}
                            className="flex items-center justify-between py-2 px-2 hover:bg-slate-800/50 transition-colors border-l-2 border-transparent hover:border-slate-600 group"
                        >
                            <div className="flex items-center gap-2">
                                {tx.type === 'Income' ? (
                                    <ArrowUpCircle className="text-emerald-500" size={14} />
                                ) : tx.type === 'Expense' ? (
                                    <ArrowDownCircle className="text-rose-500" size={14} />
                                ) : (
                                    <RefreshCw className="text-cyan-500" size={14} />
                                )}
                                <div>
                                    <p className="text-xs">{tx.description}</p>
                                    <p className="text-[10px] text-slate-600">{tx.date} • {tx.category || 'Uncategorized'}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={`text-xs font-mono-nums ${tx.type === 'Income' ? 'text-emerald-500' : tx.type === 'Expense' ? 'text-rose-500' : 'text-cyan-500'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' ? '-' : ''}{getCurrencySymbol(tx.currency || 'JPY')}{tx.amount.toLocaleString()}
                                </span>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-slate-300">
                                        <Edit size={12} />
                                    </button>
                                    <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-rose-400">
                                        <Trash2 size={12} />
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );

    return <SplitView left={leftPane} right={rightPane} leftTitle="Input & Record" rightTitle="Maintenance" />;
}
