import { useState } from 'react';
import { X, ArrowRightLeft, CreditCard, Package } from 'lucide-react';

interface RecordDrawerProps {
    isOpen: boolean;
    onClose: () => void;
}

const TABS = [
    { id: 'transaction', label: 'Transaction', icon: ArrowRightLeft },
    { id: 'debt', label: 'Debt Repayment', icon: CreditCard },
    { id: 'product', label: 'Product Update', icon: Package },
];

export default function RecordDrawer({ isOpen, onClose }: RecordDrawerProps) {
    const [activeTab, setActiveTab] = useState('transaction');
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        amount: '',
        category: '',
        description: '',
        fromAccount: '',
        toAccount: '',
        productName: '',
        location: '',
        price: '',
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        // TODO: Submit to API
        console.log('Submit:', activeTab, formData);
        onClose();
    };

    if (!isOpen) return null;

    return (
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-black/50 z-40"
                onClick={onClose}
            />

            {/* Drawer */}
            <div className="fixed right-0 top-0 h-full w-96 bg-slate-900 border-l border-slate-800 z-50 flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
                    <h2 className="text-sm font-semibold">Quick Record</h2>
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
                    >
                        <X size={18} />
                    </button>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-slate-800">
                    {TABS.map((tab) => {
                        const Icon = tab.icon;
                        const isActive = activeTab === tab.id;
                        return (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-xs transition-colors border-b-2 ${isActive
                                        ? 'border-emerald-400 text-emerald-400 bg-slate-800/50'
                                        : 'border-transparent text-slate-500 hover:text-slate-300'
                                    }`}
                            >
                                <Icon size={14} />
                                <span className="hidden sm:inline">{tab.label}</span>
                            </button>
                        );
                    })}
                </div>

                {/* Form */}
                <form onSubmit={handleSubmit} className="flex-1 p-4 overflow-auto">
                    {activeTab === 'transaction' && (
                        <div className="space-y-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                                <input
                                    type="date"
                                    value={formData.date}
                                    onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                                <input
                                    type="number"
                                    placeholder="¥0"
                                    value={formData.amount}
                                    onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <div>
                                    <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                                    <select
                                        value={formData.fromAccount}
                                        onChange={(e) => setFormData({ ...formData, fromAccount: e.target.value })}
                                        className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
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
                                        className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                    >
                                        <option value="">Select...</option>
                                        <option value="expense">Expense</option>
                                        <option value="savings">Savings</option>
                                        <option value="investment">Investment</option>
                                    </select>
                                </div>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</label>
                                <input
                                    type="text"
                                    placeholder="e.g., Food, Transport"
                                    value={formData.category}
                                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description</label>
                                <input
                                    type="text"
                                    placeholder="Optional note"
                                    value={formData.description}
                                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                        </div>
                    )}

                    {activeTab === 'debt' && (
                        <div className="space-y-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                                <input
                                    type="date"
                                    value={formData.date}
                                    onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Repayment Amount</label>
                                <input
                                    type="number"
                                    placeholder="¥0"
                                    value={formData.amount}
                                    onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Debt Account</label>
                                <select
                                    value={formData.toAccount}
                                    onChange={(e) => setFormData({ ...formData, toAccount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select debt...</option>
                                    <option value="cc-mufg">Credit Card (MUFG)</option>
                                    <option value="loan-jasso">Student Loan (JASSO)</option>
                                </select>
                            </div>
                        </div>
                    )}

                    {activeTab === 'product' && (
                        <div className="space-y-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Product Name</label>
                                <input
                                    type="text"
                                    placeholder="e.g., Milk"
                                    value={formData.productName}
                                    onChange={(e) => setFormData({ ...formData, productName: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Last Price</label>
                                <input
                                    type="number"
                                    placeholder="¥0"
                                    value={formData.price}
                                    onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Location (Store)</label>
                                <input
                                    type="text"
                                    placeholder="e.g., LIFE Supermarket"
                                    value={formData.location}
                                    onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</label>
                                <input
                                    type="text"
                                    placeholder="e.g., Groceries"
                                    value={formData.category}
                                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                        </div>
                    )}
                </form>

                {/* Submit Button */}
                <div className="p-4 border-t border-slate-800">
                    <button
                        onClick={handleSubmit}
                        className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 text-sm font-medium transition-colors"
                    >
                        Save Record
                    </button>
                </div>
            </div>
        </>
    );
}
