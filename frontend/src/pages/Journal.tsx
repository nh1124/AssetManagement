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
    getAccounts, createTransaction
} from '../api';
import { useToast } from '../components/Toast';
import type { Transaction } from '../types';

const MAIN_TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'recurring', label: 'Recurring' },
    { id: 'ai', label: 'AI' },
];

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

export default function Journal() {
    const [activeTab, setActiveTab] = useState('transaction');
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [recurringItems, setRecurringItems] = useState<any[]>([]);
    const [accounts, setAccounts] = useState<any[]>([]);
    const [isProcessing, setIsProcessing] = useState(false);
    const { showToast } = useToast();

    // Manual Input State
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
        type: 'Expense',
        from_account_id: '',
        to_account_id: '',
        frequency: 'Monthly',
        day_of_month: '1',
        month_of_year: '1',
    });

    useEffect(() => {
        fetchInitialData();
    }, []);

    const fetchInitialData = async () => {
        try {
            const [txs, recs, accs] = await Promise.all([
                getTransactions(),
                getRecurringTransactions(),
                getAccounts()
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
            await createTransaction({
                date: formData.date,
                description: formData.description,
                amount: parseFloat(formData.amount),
                type: formData.type,
                category: formData.category,
                currency: formData.currency,
                from_account: formData.fromAccount,
                to_account: formData.toAccount,
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
            for (const suggestion of suggestedTransactions) {
                await createTransaction({
                    date: suggestion.date || formData.date,
                    description: suggestion.description,
                    amount: suggestion.amount,
                    type: suggestion.type as any || 'Expense',
                    category: suggestion.category || '',
                    currency: suggestion.currency || 'JPY',
                    from_account: suggestion.from_account || 'cash',
                    to_account: suggestion.to_account || 'expense',
                });
            }
            showToast(`Saved ${suggestedTransactions.length} records`, 'success');
            setSuggestedTransactions([]);
            setAiInput('');
            setSelectedImage(null);
            fetchTransactionsOnly();
        } catch (error) {
            showToast('Failed to confirm some records', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleAddRecurring = async () => {
        if (!newRecurring.name || !newRecurring.amount) return;
        try {
            await createRecurringTransaction({
                name: newRecurring.name,
                amount: parseFloat(newRecurring.amount),
                type: newRecurring.type,
                from_account_id: parseInt(newRecurring.from_account_id) || null,
                to_account_id: parseInt(newRecurring.to_account_id) || null,
                frequency: newRecurring.frequency,
                day_of_month: parseInt(newRecurring.day_of_month),
                month_of_year: newRecurring.frequency === 'Yearly' ? parseInt(newRecurring.month_of_year) : null,
            });
            showToast('Recurring payment added', 'success');
            setShowAddRecurring(false);
            setNewRecurring({
                name: '', amount: '', type: 'Expense', from_account_id: '',
                to_account_id: '', frequency: 'Monthly', day_of_month: '1', month_of_year: '1',
            });
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (err) {
            showToast('Failed to add rule', 'error');
        }
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
                                    value={formData.fromAccount}
                                    onChange={(e) => setFormData({ ...formData, fromAccount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    <option value="cash">Cash</option>
                                    {accounts.filter(a => a.account_type === 'asset' || a.account_type === 'item').map(a => (
                                        <option key={a.id} value={a.name}>{a.name}</option>
                                    ))}
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
                                    {accounts.filter(a => a.account_type === 'expense' || a.account_type === 'income' || a.account_type === 'item').map(a => (
                                        <option key={a.id} value={a.name}>{a.name}</option>
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
                                        <button onClick={() => setSelectedImage(null)} className="absolute top-1 right-1 bg-slate-900/80 p-1 text-slate-400 hover:text-white">
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
                                            <p className="text-xs font-medium text-white">{st.description}</p>
                                            <p className="text-[10px] text-slate-500">{st.date} • {st.category} • ¥{st.amount.toLocaleString()}</p>
                                            <button onClick={() => setSuggestedTransactions(prev => prev.filter((_, i) => i !== idx))} className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-500"><X size={10} /></button>
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
                            <button onClick={() => setShowAddRecurring(true)} className="p-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded"><Plus size={14} /></button>
                        </div>
                        <div className="space-y-2">
                            {recurringItems.map((item) => (
                                <div key={item.id} className="flex items-center justify-between py-2 px-3 bg-slate-800/30 border border-slate-700 group">
                                    <div>
                                        <p className="text-xs font-medium">{item.name}</p>
                                        <p className="text-[10px] text-slate-500">{item.frequency} • ¥{item.amount.toLocaleString()}</p>
                                    </div>
                                    <button onClick={() => handleDeleteRecurring(item.id)} className="p-1 text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100"><Trash2 size={12} /></button>
                                </div>
                            ))}
                        </div>
                        {showAddRecurring && (
                            <div className="border border-cyan-800/50 bg-cyan-900/10 p-4 space-y-4 animate-in fade-in slide-in-from-top-2">
                                <div className="flex justify-between items-center border-b border-cyan-800/30 pb-2">
                                    <span className="text-[10px] font-bold text-cyan-500 uppercase">New Recurring Rule</span>
                                    <button onClick={() => setShowAddRecurring(false)} className="text-slate-500 hover:text-white"><X size={14} /></button>
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
                                            onChange={e => setNewRecurring({ ...newRecurring, type: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="Expense">Expense</option>
                                            <option value="Income">Income</option>
                                            <option value="Transfer">Transfer</option>
                                            <option value="Debt">Debt Repayment</option>
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
                                            {accounts.filter(a => a.account_type === 'asset' || a.account_type === 'item').map(a => (
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
                                            {accounts.filter(a => a.account_type === 'expense' || a.account_type === 'income' || a.account_type === 'item').map(a => (
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
                                    <button onClick={handleAddRecurring} className="flex-1 bg-cyan-600 hover:bg-cyan-500 py-2 text-xs font-bold text-white uppercase tracking-wider">Create Rule</button>
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
                                {tx.type === 'Income' ? <ArrowUpCircle className="text-emerald-500" size={14} /> : tx.type === 'Expense' ? <ArrowDownCircle className="text-rose-500" size={14} /> : <RefreshCw className="text-cyan-500" size={14} />}
                                <div>
                                    <p className="text-xs">{tx.description}</p>
                                    <p className="text-[10px] text-slate-600">{tx.date} • {tx.category || 'Other'}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={`text-xs font-mono-nums ${tx.type === 'Income' ? 'text-emerald-500' : tx.type === 'Expense' ? 'text-rose-500' : 'text-cyan-500'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' ? '-' : ''}{getCurrencySymbol(tx.currency || 'JPY')}{tx.amount.toLocaleString()}
                                </span>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100">
                                    <button className="p-1 hover:text-slate-300"><Edit size={12} /></button>
                                    <button className="p-1 hover:text-rose-400"><Trash2 size={12} /></button>
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
