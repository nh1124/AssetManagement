import { useState, useEffect } from 'react';
import { Plus, ArrowUpCircle, ArrowDownCircle, RefreshCw, CreditCard } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import SplitView from '../components/SplitView';
import TabPanel from '../components/TabPanel';
import type { Transaction } from '../types';
import { getTransactions, createTransaction } from '../api';

const mockChartData = [
    { month: 'Jan', income: 400000, expense: 280000 },
    { month: 'Feb', income: 420000, expense: 290000 },
    { month: 'Mar', income: 410000, expense: 310000 },
    { month: 'Apr', income: 450000, expense: 270000 },
    { month: 'May', income: 430000, expense: 295000 },
    { month: 'Jun', income: 460000, expense: 300000 },
];

const mockLiabilities = [
    { id: 1, name: 'Credit Card A', lender: 'MUFG', total: 100000, repaid: 55000, balance: 45000, category: 'CreditCard' },
    { id: 2, name: 'Student Loan', lender: 'JASSO', total: 2000000, repaid: 800000, balance: 1200000, category: 'Loan' },
];

const mockBuckets = [
    { asset: 'eMAXIS Slim S&P500', event: 'Retirement', allocation: 40 },
    { asset: 'Cash Savings', event: 'Emergency Fund', allocation: 100 },
    { asset: 'Individual Stocks', event: 'House Down Payment', allocation: 60 },
];

const TABS = [
    { id: 'summary', label: 'Summary' },
    { id: 'bs', label: 'B/S' },
    { id: 'pl', label: 'P/L' },
    { id: 'debt', label: 'Debt' },
    { id: 'buckets', label: 'Buckets' },
];

export default function TheLab() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [activeTab, setActiveTab] = useState('summary');
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as 'Income' | 'Expense' | 'Transfer',
        category: '',
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
            });
            setTransactions([newTransaction, ...transactions]);
            setFormData({ ...formData, description: '', amount: '', category: '' });
        } catch (error) {
            console.error('Failed to create transaction:', error);
        }
    };

    const leftPane = (
        <div className="space-y-4">
            {/* Transaction Form */}
            <form onSubmit={handleSubmit} className="space-y-2">
                <div className="grid grid-cols-2 gap-2">
                    <input
                        type="date"
                        value={formData.date}
                        onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                    />
                    <select
                        value={formData.type}
                        onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                    >
                        <option value="Expense">Expense</option>
                        <option value="Income">Income</option>
                        <option value="Transfer">Transfer</option>
                    </select>
                </div>
                <input
                    type="text"
                    placeholder="Description"
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                />
                <div className="grid grid-cols-3 gap-2">
                    <input
                        type="text"
                        placeholder="Category"
                        value={formData.category}
                        onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                    />
                    <input
                        type="number"
                        placeholder="Amount"
                        value={formData.amount}
                        onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500 font-mono-nums"
                    />
                    <button
                        type="submit"
                        className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                    >
                        <Plus size={14} /> Add
                    </button>
                </div>
            </form>

            {/* Transaction List */}
            <div className="border-t border-slate-800 pt-3">
                <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Recent Transactions</h3>
                <div className="space-y-0.5">
                    {transactions.length === 0 ? (
                        <p className="text-slate-600 text-xs py-4 text-center">No transactions yet</p>
                    ) : (
                        transactions.map((tx) => (
                            <div
                                key={tx.id}
                                className="flex items-center justify-between py-1.5 px-2 hover:bg-slate-800/50 transition-colors border-l-2 border-transparent hover:border-slate-600"
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
                                        <p className="text-[10px] text-slate-600">{tx.date}</p>
                                    </div>
                                </div>
                                <span className={`text-xs font-mono-nums ${tx.type === 'Income' ? 'text-emerald-500' : tx.type === 'Expense' ? 'text-rose-500' : 'text-cyan-500'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' ? '-' : ''}¥{tx.amount.toLocaleString()}
                                </span>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );

    const renderTabContent = () => {
        switch (activeTab) {
            case 'summary':
                return (
                    <div className="space-y-4">
                        <div className="h-48">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={mockChartData}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                                    <XAxis dataKey="month" stroke="#64748b" fontSize={10} />
                                    <YAxis stroke="#64748b" fontSize={10} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }}
                                    />
                                    <Bar dataKey="income" fill="#34d399" />
                                    <Bar dataKey="expense" fill="#f87171" />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                );
            case 'debt':
                return (
                    <div className="space-y-2">
                        <div className="grid grid-cols-5 text-[10px] text-slate-500 uppercase tracking-wider border-b border-slate-800 pb-1">
                            <span>Name</span>
                            <span>Lender</span>
                            <span className="text-right">Total</span>
                            <span className="text-right">Repaid</span>
                            <span className="text-right">Balance</span>
                        </div>
                        {mockLiabilities.map((l) => (
                            <div key={l.id} className="grid grid-cols-5 text-xs py-1.5 border-b border-slate-800/50">
                                <span className="flex items-center gap-1">
                                    <CreditCard size={12} className="text-rose-400" />
                                    {l.name}
                                </span>
                                <span className="text-slate-400">{l.lender}</span>
                                <span className="text-right font-mono-nums">¥{l.total.toLocaleString()}</span>
                                <span className="text-right font-mono-nums text-emerald-500">¥{l.repaid.toLocaleString()}</span>
                                <span className="text-right font-mono-nums text-rose-400">¥{l.balance.toLocaleString()}</span>
                            </div>
                        ))}
                    </div>
                );
            case 'buckets':
                return (
                    <div className="space-y-2">
                        <div className="grid grid-cols-3 text-[10px] text-slate-500 uppercase tracking-wider border-b border-slate-800 pb-1">
                            <span>Asset</span>
                            <span>Life Event</span>
                            <span className="text-right">Allocation</span>
                        </div>
                        {mockBuckets.map((b, i) => (
                            <div key={i} className="grid grid-cols-3 text-xs py-1.5 border-b border-slate-800/50">
                                <span>{b.asset}</span>
                                <span className="text-amber-400">{b.event}</span>
                                <span className="text-right font-mono-nums">{b.allocation}%</span>
                            </div>
                        ))}
                    </div>
                );
            default:
                return <div className="text-xs text-slate-500">Tab content coming soon...</div>;
        }
    };

    const rightPane = (
        <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
            {renderTabContent()}
        </TabPanel>
    );

    return <SplitView left={leftPane} right={rightPane} leftTitle="Input & Records" rightTitle="Analytics" />;
}
