import { useState } from 'react';
import { X, ArrowRightLeft } from 'lucide-react';

interface QuickInputDrawerProps {
    isOpen: boolean;
    onClose: () => void;
}

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

export default function QuickInputDrawer({ isOpen, onClose }: QuickInputDrawerProps) {
    const [formData, setFormData] = useState({
        amount: '',
        category: '',
        currency: 'JPY',
        fromAccount: '',
        toAccount: '',
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        // TODO: Submit to API
        console.log('Quick submit:', formData);
        setFormData({ amount: '', category: '', currency: 'JPY', fromAccount: '', toAccount: '' });
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
            <div className="fixed right-0 top-0 h-full w-80 bg-slate-900 border-l border-slate-800 z-50 flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
                    <div className="flex items-center gap-2">
                        <ArrowRightLeft size={16} className="text-emerald-400" />
                        <h2 className="text-sm font-semibold">Quick Record</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
                    >
                        <X size={18} />
                    </button>
                </div>

                {/* Form */}
                <form onSubmit={handleSubmit} className="flex-1 p-4 space-y-4">
                    {/* Amount + Currency */}
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                        <div className="flex gap-2">
                            <input
                                type="number"
                                placeholder="0"
                                value={formData.amount}
                                onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                className="flex-1 bg-slate-800 border border-slate-700 px-3 py-2 text-lg font-mono-nums focus:outline-none focus:border-emerald-500"
                                autoFocus
                            />
                            <select
                                value={formData.currency}
                                onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                                className="w-20 bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                {CURRENCIES.map((c) => (
                                    <option key={c} value={c}>{c}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    {/* Category */}
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

                    {/* Source/Destination */}
                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From</label>
                            <select
                                value={formData.fromAccount}
                                onChange={(e) => setFormData({ ...formData, fromAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select...</option>
                                <option value="cash">Cash</option>
                                <option value="bank">Bank</option>
                                <option value="credit">Credit Card</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To</label>
                            <select
                                value={formData.toAccount}
                                onChange={(e) => setFormData({ ...formData, toAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select...</option>
                                <option value="expense">Expense</option>
                                <option value="savings">Savings</option>
                                <option value="investment">Investment</option>
                            </select>
                        </div>
                    </div>
                </form>

                {/* Submit Button */}
                <div className="p-4 border-t border-slate-800">
                    <button
                        onClick={handleSubmit}
                        className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-3 text-sm font-medium transition-colors"
                    >
                        Save
                    </button>
                </div>
            </div>
        </>
    );
}
