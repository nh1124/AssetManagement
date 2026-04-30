import { useState, useEffect, useRef } from 'react';
import {
    Trash2, Plus, Sparkles, Send, Loader2, ImagePlus, X,
    ArrowUpCircle, ArrowDownCircle, RefreshCw, Edit
} from 'lucide-react';
import TabPanel from '../components/TabPanel';
import SplitView from '../components/SplitView';
import {
    getTransactions, getRecurringTransactions,
    createRecurringTransaction, deleteRecurringTransaction,
    getAccounts, createTransaction, deleteTransaction,
} from '../api';
import { useToast } from '../components/Toast';
import type { Transaction } from '../types';

const MAIN_TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'recurring', label: 'Recurring' },
    { id: 'ai', label: 'AI' },
];

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];
type TransactionKind =
    | 'Income'
    | 'Expense'
    | 'Transfer'
    | 'LiabilityPayment'
    | 'Borrowing'
    | 'CreditExpense'
    | 'CreditAssetPurchase';

interface AccountItem {
    id: number;
    name: string;
    account_type: string;
    balance?: number;
}

const TRANSACTION_TYPES: Array<{
    value: TransactionKind;
    label: string;
    description: string;
    fromTypes: string[];
    toTypes: string[];
}> = [
    {
        value: 'Expense',
        label: 'Expense',
        description: 'Pay cash/bank/card asset now. Dr expense or item, Cr asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['expense', 'item'],
    },
    {
        value: 'Income',
        label: 'Income',
        description: 'Receive income into cash/bank. Dr asset, Cr income.',
        fromTypes: ['income'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'Transfer',
        label: 'Transfer',
        description: 'Move value between asset accounts. Dr destination asset, Cr source asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'Borrowing',
        label: 'Borrowing',
        description: 'Borrow loan/cash advance and increase assets. Dr asset, Cr liability.',
        fromTypes: ['liability'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'CreditExpense',
        label: 'Credit Expense',
        description: 'Buy expenses on credit. Dr expense, Cr liability.',
        fromTypes: ['liability'],
        toTypes: ['expense', 'item'],
    },
    {
        value: 'CreditAssetPurchase',
        label: 'Credit Asset Purchase',
        description: 'Buy an asset/item with credit or a loan. Dr asset or item, Cr liability.',
        fromTypes: ['liability'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'LiabilityPayment',
        label: 'Debt Repayment',
        description: 'Repay debt from cash/bank. Dr liability, Cr asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['liability'],
    },
];

const ACCOUNT_RULES = Object.fromEntries(
    TRANSACTION_TYPES.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<TransactionKind, { fromTypes: string[]; toTypes: string[] }>;

const typeDescription = (type: string) =>
    TRANSACTION_TYPES.find((option) => option.value === type)?.description ?? '';

export default function Journal() {
    const [activeTab, setActiveTab] = useState('transaction');
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [recurringItems, setRecurringItems] = useState<any[]>([]);
    const [accounts, setAccounts] = useState<AccountItem[]>([]);
    const [isProcessing, setIsProcessing] = useState(false);
    const { showToast } = useToast();

    // Manual Input State
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as TransactionKind,
        category: '',
        currency: 'JPY',
        fromAccountId: '',
        toAccountId: '',
    });

    // AI State
    const [aiInput, setAiInput] = useState('');
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const [suggestedTransactions, setSuggestedTransactions] = useState<any[]>([]);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Recurring State
    const [showAddRecurring, setShowAddRecurring] = useState(false);
    const [newRecurring, setNewRecurring] = useState({
        name: '',
        amount: '',
        type: 'Expense' as TransactionKind,
        from_account_id: '',
        to_account_id: '',
        frequency: 'Monthly',
        day_of_month: '1',
        month_of_year: '1',
    });

    const fromAccounts = accounts.filter((a) => ACCOUNT_RULES[formData.type].fromTypes.includes(a.account_type));
    const toAccounts = accounts.filter((a) => ACCOUNT_RULES[formData.type].toTypes.includes(a.account_type));
    const recurringFromAccounts = accounts.filter((a) => ACCOUNT_RULES[newRecurring.type].fromTypes.includes(a.account_type));
    const recurringToAccounts = accounts.filter((a) => ACCOUNT_RULES[newRecurring.type].toTypes.includes(a.account_type));

    useEffect(() => {
        fetchInitialData();
    }, []);

    useEffect(() => {
        setFormData((prev) => {
            const nextFrom = fromAccounts.find((acc) => String(acc.id) === prev.fromAccountId)
                ? prev.fromAccountId
                : (fromAccounts[0] ? String(fromAccounts[0].id) : '');
            const nextTo = toAccounts.find((acc) => String(acc.id) === prev.toAccountId)
                ? prev.toAccountId
                : (toAccounts[0] ? String(toAccounts[0].id) : '');

            if (nextFrom === prev.fromAccountId && nextTo === prev.toAccountId) {
                return prev;
            }
            return {
                ...prev,
                fromAccountId: nextFrom,
                toAccountId: nextTo,
            };
        });
    }, [formData.type, accounts.length]);

    const fetchInitialData = async () => {
        try {
            const [txs, recs, accs] = await Promise.all([
                getTransactions(),
                getRecurringTransactions(),
                getAccounts(),
            ]);
            setTransactions(txs);
            setRecurringItems(recs);
            setAccounts(accs);
        } catch (error) {
            console.error('Failed to fetch journal data:', error);
            showToast('Failed to load data', 'error');
        }
    };

    const fetchTransactionsOnly = async () => {
        try {
            const txs = await getTransactions();
            setTransactions(txs);
        } catch (error) {
            console.error('Failed to update transactions:', error);
        }
    };

    const getCurrencySymbol = (currency: string) => {
        const symbols: Record<string, string> = { JPY: '¥', USD: '$', EUR: '€', GBP: '£', CNY: '¥' };
        return symbols[currency] || currency;
    };

    const handleRecordSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!formData.description || !formData.amount) return;
        setIsProcessing(true);
        try {
            const fromAccountId = formData.fromAccountId ? parseInt(formData.fromAccountId, 10) : undefined;
            const toAccountId = formData.toAccountId ? parseInt(formData.toAccountId, 10) : undefined;
            const toAccount = toAccounts.find((acc) => acc.id === toAccountId);

            await createTransaction({
                date: formData.date,
                description: formData.description,
                amount: parseFloat(formData.amount),
                type: formData.type,
                category: formData.category || toAccount?.name || '',
                currency: formData.currency,
                from_account_id: fromAccountId,
                to_account_id: toAccountId,
            });
            showToast('Record saved', 'success');
            setFormData({ ...formData, description: '', amount: '', category: '' });
            fetchTransactionsOnly();
        } catch (error) {
            showToast('Failed to save record', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleAiSubmit = async () => {
        if (!aiInput.trim() && !selectedImage) return;
        setIsProcessing(true);
        try {
            const parts: any[] = [];
            if (aiInput) parts.push({ text: aiInput });
            if (selectedImage) {
                const base64Data = selectedImage.split(',')[1];
                const mimeType = selectedImage.split(';')[0].split(':')[1];
                parts.push({ inline_data: { mime_type: mimeType, data: base64Data } });
            }
            const { analyzeWithBackend } = await import('../api');
            const results = await analyzeWithBackend({ parts });
            if (Array.isArray(results)) setSuggestedTransactions(results);
        } catch (error) {
            showToast('AI analysis failed', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleConfirmSuggestions = async () => {
        setIsProcessing(true);
        try {
            let processedCount = 0;
            const resolveAccountId = (
                accountName: string | undefined,
                candidateTypes: string[],
                fallbackToFirst: boolean
            ): number | undefined => {
                if (accountName) {
                    const matched = accounts.find(
                        (acc) =>
                            candidateTypes.includes(acc.account_type) &&
                            acc.name.toLowerCase() === accountName.toLowerCase()
                    );
                    if (matched) return matched.id;
                }
                if (!fallbackToFirst) return undefined;
                const first = accounts.find((acc) => candidateTypes.includes(acc.account_type));
                return first?.id;
            };

            for (const suggestion of suggestedTransactions) {
                const txType = (suggestion.type as TransactionKind) || 'Expense';
                const rules = ACCOUNT_RULES[txType];
                if (suggestion.is_recurring) {
                    // Map account names to IDs for recurring transaction
                    const fromAccountId = resolveAccountId(suggestion.from_account, rules.fromTypes, true);
                    const toAccountId = resolveAccountId(suggestion.to_account, rules.toTypes, true);

                    await createRecurringTransaction({
                        name: suggestion.description,
                        amount: suggestion.amount,
                        type: txType,
                        from_account_id: fromAccountId ?? null,
                        to_account_id: toAccountId ?? null,
                        frequency: suggestion.frequency || 'Monthly',
                        day_of_month: suggestion.day_of_month || 1,
                        month_of_year: suggestion.frequency === 'Yearly' ? (suggestion.month_of_year || 1) : null,
                    });
                } else {
                    const fromAccountId = resolveAccountId(suggestion.from_account, rules.fromTypes, true);
                    const toAccountId = resolveAccountId(suggestion.to_account, rules.toTypes, true);
                    const toAccount = accounts.find((acc) => acc.id === toAccountId);

                    await createTransaction({
                        date: suggestion.date || formData.date,
                        description: suggestion.description,
                        amount: suggestion.amount,
                        type: txType,
                        category: suggestion.category || toAccount?.name || '',
                        currency: suggestion.currency || 'JPY',
                        from_account_id: fromAccountId,
                        to_account_id: toAccountId,
                    });
                }
                processedCount++;
            }
            showToast(`Saved ${processedCount} records`, 'success');
            setSuggestedTransactions([]);
            setAiInput('');
            setSelectedImage(null);
            fetchTransactionsOnly();
            // Refresh recurring items as well
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (error) {
            console.error(error);
            showToast('Failed to confirm some records', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleDeleteTransaction = async (id: number) => {
        try {
            await deleteTransaction(id);
            showToast('Transaction deleted', 'info');
            fetchTransactionsOnly();
        } catch (error) {
            showToast('Failed to delete transaction', 'error');
        }
    };

    const [editingRecurringId, setEditingRecurringId] = useState<number | null>(null); // State for editing

    const handleAddRecurring = async () => {
        if (!newRecurring.name || !newRecurring.amount) return;
        try {
            const payload = {
                name: newRecurring.name,
                amount: parseFloat(newRecurring.amount),
                type: newRecurring.type,
                from_account_id: parseInt(newRecurring.from_account_id) || null,
                to_account_id: parseInt(newRecurring.to_account_id) || null,
                frequency: newRecurring.frequency,
                day_of_month: parseInt(newRecurring.day_of_month),
                month_of_year: newRecurring.frequency === 'Yearly' ? parseInt(newRecurring.month_of_year) : null,
            };

            if (editingRecurringId) {
                // Update existing rule
                const { updateRecurringTransaction } = await import('../api');
                await updateRecurringTransaction(editingRecurringId, payload);
                showToast('Recurring payment updated', 'success');
            } else {
                // Create new rule
                await createRecurringTransaction(payload);
                showToast('Recurring payment added', 'success');
            }

            setShowAddRecurring(false);
            setEditingRecurringId(null);
            setNewRecurring({
                name: '', amount: '', type: 'Expense', from_account_id: '',
                to_account_id: '', frequency: 'Monthly', day_of_month: '1', month_of_year: '1',
            });
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (err) {
            showToast('Failed to save rule', 'error');
        }
    };

    const handleEditRecurring = (item: any) => {
        setNewRecurring({
            name: item.name,
            amount: item.amount.toString(),
            type: item.type as TransactionKind,
            from_account_id: item.from_account_id ? item.from_account_id.toString() : '',
            to_account_id: item.to_account_id ? item.to_account_id.toString() : '',
            frequency: item.frequency,
            day_of_month: item.day_of_month.toString(),
            month_of_year: item.month_of_year ? item.month_of_year.toString() : '1',
        });
        setEditingRecurringId(item.id);
        setShowAddRecurring(true);
    };

    const handleDeleteRecurring = async (id: number) => {
        try {
            await deleteRecurringTransaction(id);
            showToast('Rule deleted', 'info');
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (err) {
            showToast('Failed to delete rule', 'error');
        }
    };

    const leftPane = (
        <TabPanel tabs={MAIN_TABS} activeTab={activeTab} onTabChange={setActiveTab}>
            <div className="py-2">
                {activeTab === 'transaction' && (
                    <form onSubmit={handleRecordSubmit} className="space-y-4 pt-2">
                        <div className="grid grid-cols-2 gap-3">
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
                                    onChange={(e) => setFormData({ ...formData, type: e.target.value as TransactionKind })}
                                    title={typeDescription(formData.type)}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    {TRANSACTION_TYPES.map((option) => (
                                        <option key={option.value} value={option.value} title={option.description}>
                                            {option.label}
                                        </option>
                                    ))}
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

                        <div className="grid grid-cols-2 gap-3">
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

                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                                <select
                                    value={formData.fromAccountId}
                                    onChange={(e) => setFormData({ ...formData, fromAccountId: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    {fromAccounts.map((a) => (
                                        <option key={a.id} value={a.id}>{a.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To Account</label>
                                <select
                                    value={formData.toAccountId}
                                    onChange={(e) => setFormData({ ...formData, toAccountId: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    {toAccounts.map((a) => (
                                        <option key={a.id} value={a.id}>{a.name}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <button
                            type="submit"
                            disabled={isProcessing}
                            className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                        >
                            {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                            Save Transaction
                        </button>
                    </form>
                )}

                {activeTab === 'ai' && (
                    <div className="space-y-4 pt-2">
                        {!suggestedTransactions.length ? (
                            <>
                                <div className="border border-amber-800/50 bg-amber-900/10 p-2 text-xs flex items-center gap-2 text-amber-400">
                                    <Sparkles size={12} /> Multi-record extraction from text or images
                                </div>
                                <textarea
                                    placeholder="e.g., Lunch 1200 yen and Grocery 3500 yen"
                                    value={aiInput}
                                    onChange={(e) => setAiInput(e.target.value)}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500 h-24 resize-none"
                                />
                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={() => fileInputRef.current?.click()}
                                        className="flex-1 bg-slate-800 border border-dashed border-slate-600 hover:border-amber-500 py-3 flex items-center justify-center gap-2 text-xs text-slate-400 hover:text-amber-400 transition-colors"
                                    >
                                        <ImagePlus size={16} /> {selectedImage ? 'Change Image' : 'Upload Image'}
                                    </button>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        accept="image/*"
                                        onChange={(e) => {
                                            const file = e.target.files?.[0];
                                            if (file) {
                                                const reader = new FileReader();
                                                reader.onloadend = () => setSelectedImage(reader.result as string);
                                                reader.readAsDataURL(file);
                                            }
                                        }}
                                        className="hidden"
                                    />
                                </div>
                                {selectedImage && (
                                    <div className="relative">
                                        <img src={selectedImage} alt="Preview" className="w-full h-32 object-cover border border-slate-700" />
                                        <button
                                            type="button"
                                            onClick={() => setSelectedImage(null)}
                                            className="absolute top-1 right-1 bg-slate-900/80 p-1 text-slate-400 hover:text-white"
                                            aria-label="Remove selected image"
                                            title="Remove selected image"
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
                            <div className="space-y-3">
                                <div className="flex justify-between items-center">
                                    <h3 className="text-[10px] text-amber-500 font-bold uppercase tracking-widest">Suggestions</h3>
                                    <button onClick={() => setSuggestedTransactions([])} className="text-[10px] text-slate-500 hover:text-white">Discard</button>
                                </div>
                                <div className="space-y-2 max-h-60 overflow-auto pr-1">
                                    {suggestedTransactions.map((st, idx) => (
                                        <div key={idx} className="bg-slate-800/50 border border-slate-700 p-2 relative group">
                                            <div className="flex justify-between items-start">
                                                <p className="text-xs font-medium text-white">{st.description}</p>
                                                {st.is_recurring && (
                                                    <span className="text-[8px] bg-cyan-900/50 text-cyan-400 px-1 rounded border border-cyan-800/50">Recurring</span>
                                                )}
                                            </div>
                                            <p className="text-[10px] text-slate-500">
                                                {st.is_recurring
                                                    ? `${st.frequency} (Day ${st.day_of_month})`
                                                    : st.date}
                                                • {st.category} • ¥{st.amount.toLocaleString()}
                                            </p>
                                            <button
                                                type="button"
                                                onClick={() => setSuggestedTransactions(prev => prev.filter((_, i) => i !== idx))}
                                                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-500"
                                                aria-label="Remove suggestion"
                                                title="Remove suggestion"
                                            >
                                                <X size={10} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                                <button onClick={handleConfirmSuggestions} disabled={isProcessing} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-2 text-xs font-bold transition-all">
                                    {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                    Confirm & Save All ({suggestedTransactions.length})
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'recurring' && (
                    <div className="space-y-3 pt-2">
                        <div className="flex items-center justify-between">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Automation Rules</h3>
                            <button
                                type="button"
                                onClick={() => {
                                    setShowAddRecurring(true);
                                    setEditingRecurringId(null);
                                    setNewRecurring({
                                        name: '', amount: '', type: 'Expense', from_account_id: '',
                                        to_account_id: '', frequency: 'Monthly', day_of_month: '1', month_of_year: '1',
                                    });
                                }}
                                className="p-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded"
                                aria-label="Add recurring rule"
                                title="Add recurring rule"
                            >
                                <Plus size={14} />
                            </button>
                        </div>
                        <div className="space-y-2">
                            {recurringItems.map((item) => (
                                <div key={item.id} className="flex items-center justify-between py-2 px-3 bg-slate-800/30 border border-slate-700 group">
                                    <div>
                                        <p className="text-xs font-medium">{item.name}</p>
                                        <p className="text-[10px] text-slate-500">{item.frequency} • ¥{item.amount.toLocaleString()}</p>
                                    </div>
                                    <div className="flex gap-1 opacity-0 group-hover:opacity-100">
                                        <button
                                            type="button"
                                            onClick={() => handleEditRecurring(item)}
                                            className="p-1 text-slate-500 hover:text-cyan-400"
                                            aria-label="Edit recurring rule"
                                            title="Edit recurring rule"
                                        >
                                            <Edit size={12} />
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => handleDeleteRecurring(item.id)}
                                            className="p-1 text-slate-500 hover:text-rose-400"
                                            aria-label="Delete recurring rule"
                                            title="Delete recurring rule"
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                        {showAddRecurring && (
                            <div className="border border-cyan-800/50 bg-cyan-900/10 p-4 space-y-4 animate-in fade-in slide-in-from-top-2">
                                <div className="flex justify-between items-center border-b border-cyan-800/30 pb-2">
                                    <span className="text-[10px] font-bold text-cyan-500 uppercase">{editingRecurringId ? 'Edit Recurring Rule' : 'New Recurring Rule'}</span>
                                    <button
                                        type="button"
                                        onClick={() => setShowAddRecurring(false)}
                                        className="text-slate-500 hover:text-white"
                                        aria-label="Close recurring modal"
                                        title="Close recurring modal"
                                    >
                                        <X size={14} />
                                    </button>
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div className="col-span-2">
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Rule Name</label>
                                        <input
                                            type="text"
                                            placeholder="e.g., Rent, Netflix"
                                            value={newRecurring.name}
                                            onChange={e => setNewRecurring({ ...newRecurring, name: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                                        <div className="relative">
                                            <span className="absolute left-2 top-1.5 text-slate-500 text-xs">¥</span>
                                            <input
                                                type="number"
                                                value={newRecurring.amount}
                                                onChange={e => setNewRecurring({ ...newRecurring, amount: e.target.value })}
                                                className="w-full bg-slate-900 border border-slate-700 pl-6 pr-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                            />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Type</label>
                                        <select
                                            value={newRecurring.type}
                                            onChange={e => {
                                                const nextType = e.target.value as TransactionKind;
                                                setNewRecurring({ ...newRecurring, type: nextType, from_account_id: '', to_account_id: '' });
                                            }}
                                            title={typeDescription(newRecurring.type)}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            {TRANSACTION_TYPES.map((option) => (
                                                <option key={option.value} value={option.value} title={option.description}>
                                                    {option.label}
                                                </option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                                        <select
                                            value={newRecurring.from_account_id}
                                            onChange={e => setNewRecurring({ ...newRecurring, from_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {recurringFromAccounts.map(a => (
                                                <option key={a.id} value={a.id}>{a.name}</option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To Account</label>
                                        <select
                                            value={newRecurring.to_account_id}
                                            onChange={e => setNewRecurring({ ...newRecurring, to_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {recurringToAccounts.map(a => (
                                                <option key={a.id} value={a.id}>{a.name}</option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Frequency</label>
                                        <select
                                            value={newRecurring.frequency}
                                            onChange={e => setNewRecurring({ ...newRecurring, frequency: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="Monthly">Monthly</option>
                                            <option value="Yearly">Yearly</option>
                                        </select>
                                    </div>

                                    {newRecurring.frequency === 'Monthly' ? (
                                        <div>
                                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Day of Month</label>
                                            <input
                                                type="number"
                                                min="1"
                                                max="31"
                                                value={newRecurring.day_of_month}
                                                onChange={e => setNewRecurring({ ...newRecurring, day_of_month: e.target.value })}
                                                className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                            />
                                        </div>
                                    ) : (
                                        <>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Month</label>
                                                <select
                                                    value={newRecurring.month_of_year}
                                                    onChange={e => setNewRecurring({ ...newRecurring, month_of_year: e.target.value })}
                                                    className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                                >
                                                    <option value="1">January</option>
                                                    <option value="2">February</option>
                                                    <option value="3">March</option>
                                                    <option value="4">April</option>
                                                    <option value="5">May</option>
                                                    <option value="6">June</option>
                                                    <option value="7">July</option>
                                                    <option value="8">August</option>
                                                    <option value="9">September</option>
                                                    <option value="10">October</option>
                                                    <option value="11">November</option>
                                                    <option value="12">December</option>
                                                </select>
                                            </div>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Day</label>
                                                <input
                                                    type="number"
                                                    min="1"
                                                    max="31"
                                                    value={newRecurring.day_of_month}
                                                    onChange={e => setNewRecurring({ ...newRecurring, day_of_month: e.target.value })}
                                                    className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                                />
                                            </div>
                                        </>
                                    )}
                                </div>

                                <div className="flex gap-2 pt-2">
                                    <button onClick={handleAddRecurring} className="flex-1 bg-cyan-600 hover:bg-cyan-500 py-2 text-xs font-bold text-white uppercase tracking-wider">
                                        {editingRecurringId ? 'Update Rule' : 'Create Rule'}
                                    </button>
                                    <button onClick={() => setShowAddRecurring(false)} className="px-4 bg-slate-800 hover:bg-slate-700 py-2 text-xs font-bold text-slate-400 uppercase">Cancel</button>
                                </div>
                            </div>
                        )}
                    </div>
                )}

            </div>
        </TabPanel>
    );

    const rightPane = (
        <div className="space-y-3 h-full flex flex-col">
            <div className="flex-1 overflow-auto space-y-0.5">
                {transactions.length === 0 ? (
                    <p className="text-slate-600 text-xs py-8 text-center">No transactions yet</p>
                ) : (
                    transactions.map((tx) => (
                        <div key={tx.id} className="flex items-center justify-between py-2 px-2 hover:bg-slate-800/50 transition-colors group">
                            <div className="flex items-center gap-2">
                                {tx.type === 'Income' ? <ArrowUpCircle className="text-emerald-500" size={14} /> : tx.type === 'Expense' || tx.type === 'LiabilityPayment' ? <ArrowDownCircle className="text-rose-500" size={14} /> : <RefreshCw className="text-cyan-500" size={14} />}
                                <div>
                                    <p className="text-xs">{tx.description}</p>
                                    <p className="text-[10px] text-slate-600">{tx.date} • {tx.category || 'Other'}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={`text-xs font-mono-nums ${tx.type === 'Income' ? 'text-emerald-500' : tx.type === 'Expense' || tx.type === 'LiabilityPayment' ? 'text-rose-500' : 'text-cyan-500'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' || tx.type === 'LiabilityPayment' ? '-' : ''}{getCurrencySymbol(tx.currency || 'JPY')}{tx.amount.toLocaleString()}
                                </span>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100">
                                    <button
                                        type="button"
                                        className="p-1 hover:text-slate-300"
                                        aria-label="Edit transaction"
                                        title="Edit transaction"
                                    >
                                        <Edit size={12} />
                                    </button>
                                    <button
                                        type="button"
                                        className="p-1 hover:text-rose-400"
                                        onClick={() => handleDeleteTransaction(tx.id)}
                                        aria-label="Delete transaction"
                                        title="Delete transaction"
                                    >
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

    return (
        <div className="h-full flex flex-col p-2 overflow-hidden">
            <SplitView
                left={leftPane}
                right={rightPane}
                leftTitle="Input & Rule Management"
                rightTitle="Transaction Journal"
            />
        </div>
    );
}
