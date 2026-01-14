import { useState, useEffect } from 'react';
import { Plus, ArrowUpCircle, ArrowDownCircle, RefreshCw, Edit, Trash2, CreditCard, Package } from 'lucide-react';
import SplitView from '../components/SplitView';
import TabPanel from '../components/TabPanel';
import type { Transaction } from '../types';
import { getTransactions, createTransaction } from '../api';

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

const INPUT_TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'debt', label: 'Debt Repayment' },
    { id: 'product', label: 'Product' },
];

export default function RecordPage() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [activeTab, setActiveTab] = useState('transaction');
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as 'Income' | 'Expense' | 'Transfer',
        category: '',
        currency: 'JPY',
        fromAccount: '',
        toAccount: '',
    });

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

    const getCurrencySymbol = (currency: string) => {
        const symbols: Record<string, string> = { JPY: '¥', USD: '$', EUR: '€', GBP: '£', CNY: '¥' };
        return symbols[currency] || currency;
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

                    <div className="grid grid-cols-3 gap-2">
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
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</label>
                            <input
                                type="text"
                                placeholder="e.g., Food"
                                value={formData.category}
                                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            />
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

            {activeTab === 'debt' && (
                <form className="space-y-3">
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                        <input
                            type="date"
                            defaultValue={new Date().toISOString().split('T')[0]}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                    </div>
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Debt Account</label>
                        <select className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500">
                            <option value="">Select debt...</option>
                            <option value="cc-mufg">Credit Card (MUFG)</option>
                            <option value="loan">Student Loan</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Repayment Amount</label>
                        <input
                            type="number"
                            placeholder="0"
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                        />
                    </div>
                    <button className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors">
                        <CreditCard size={14} /> Record Repayment
                    </button>
                </form>
            )}

            {activeTab === 'product' && (
                <form className="space-y-3">
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Product Name</label>
                        <input
                            type="text"
                            placeholder="e.g., Milk"
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Price</label>
                            <input
                                type="number"
                                placeholder="0"
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Location</label>
                            <input
                                type="text"
                                placeholder="Store name"
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                    </div>
                    <button className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors">
                        <Package size={14} /> Save Product
                    </button>
                </form>
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
