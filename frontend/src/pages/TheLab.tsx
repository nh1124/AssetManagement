import { useState, useEffect } from 'react';
import { Plus, ArrowUpCircle, ArrowDownCircle, RefreshCw } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import SplitView from '../components/SplitView';
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

export default function TheLab() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [activeTab, setActiveTab] = useState<'summary' | 'bs' | 'pl'>('summary');
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as 'Income' | 'Expense' | 'Transfer',
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
            });
            setTransactions([newTransaction, ...transactions]);
            setFormData({ ...formData, description: '', amount: '' });
        } catch (error) {
            console.error('Failed to create transaction:', error);
        }
    };

    const leftPane = (
        <div className="space-y-6">
            {/* Transaction Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                    <input
                        type="date"
                        value={formData.date}
                        onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                        className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    />
                    <select
                        value={formData.type}
                        onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                        className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
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
                    className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <div className="flex gap-3">
                    <input
                        type="number"
                        placeholder="Amount"
                        value={formData.amount}
                        onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                        className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    />
                    <button
                        type="submit"
                        className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-colors"
                    >
                        <Plus size={16} /> Add
                    </button>
                </div>
            </form>

            {/* Transaction List */}
            <div className="space-y-2">
                <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Recent Transactions</h3>
                <div className="space-y-1 max-h-[400px] overflow-auto">
                    {transactions.length === 0 ? (
                        <p className="text-slate-500 text-sm py-4 text-center">No transactions yet</p>
                    ) : (
                        transactions.map((tx) => (
                            <div
                                key={tx.id}
                                className="flex items-center justify-between p-3 bg-slate-700/50 rounded-lg hover:bg-slate-700 transition-colors"
                            >
                                <div className="flex items-center gap-3">
                                    {tx.type === 'Income' ? (
                                        <ArrowUpCircle className="text-emerald-400" size={18} />
                                    ) : tx.type === 'Expense' ? (
                                        <ArrowDownCircle className="text-rose-400" size={18} />
                                    ) : (
                                        <RefreshCw className="text-cyan-400" size={18} />
                                    )}
                                    <div>
                                        <p className="text-sm font-medium">{tx.description}</p>
                                        <p className="text-xs text-slate-500">{tx.date}</p>
                                    </div>
                                </div>
                                <span className={`text-sm font-medium ${tx.type === 'Income' ? 'text-emerald-400' : tx.type === 'Expense' ? 'text-rose-400' : 'text-cyan-400'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' ? '-' : ''}¥{tx.amount.toLocaleString()}
                                </span>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );

    const rightPane = (
        <div className="space-y-4">
            {/* Tab Navigation */}
            <div className="flex space-x-1 bg-slate-800 rounded-lg p-1">
                {(['summary', 'bs', 'pl'] as const).map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${activeTab === tab
                            ? 'bg-slate-700 text-emerald-400'
                            : 'text-slate-400 hover:text-slate-200'
                            }`}
                    >
                        {tab === 'summary' ? 'Summary' : tab === 'bs' ? 'B/S' : 'P/L'}
                    </button>
                ))}
            </div>

            {/* Chart */}
            <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={mockChartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="month" stroke="#94a3b8" fontSize={12} />
                        <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={(v) => `¥${(v / 1000).toFixed(0)}k`} />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                            labelStyle={{ color: '#f1f5f9' }}
                        />
                        <Bar dataKey="income" fill="#34d399" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="expense" fill="#f87171" radius={[4, 4, 0, 0]} />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* Liability Watch */}
            <div className="bg-slate-700/50 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">Liability Watch</h3>
                <div className="space-y-2">
                    <div className="flex justify-between items-center">
                        <span className="text-sm text-slate-300">Credit Card A</span>
                        <span className="text-sm font-medium text-rose-400">¥45,000</span>
                    </div>
                    <div className="flex justify-between items-center">
                        <span className="text-sm text-slate-300">Student Loan</span>
                        <span className="text-sm font-medium text-amber-400">¥1,200,000</span>
                    </div>
                </div>
            </div>
        </div>
    );

    return <SplitView left={leftPane} right={rightPane} leftTitle="Input & Records" rightTitle="Analytics" />;
}
