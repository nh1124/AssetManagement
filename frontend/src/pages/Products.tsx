import { useState } from 'react';
import { Plus, Trash2, Edit, Package } from 'lucide-react';

const mockProducts = [
    { id: 1, name: 'Milk', category: 'Groceries', lastPrice: 198, frequency: 7, lastPurchase: '2026-01-10' },
    { id: 2, name: 'Detergent', category: 'Household', lastPrice: 498, frequency: 30, lastPurchase: '2026-01-01' },
    { id: 3, name: 'Rice 5kg', category: 'Groceries', lastPrice: 1980, frequency: 45, lastPurchase: '2025-12-20' },
    { id: 4, name: 'Eggs (10)', category: 'Groceries', lastPrice: 298, frequency: 10, lastPurchase: '2026-01-08' },
    { id: 5, name: 'Coffee Beans', category: 'Groceries', lastPrice: 1280, frequency: 21, lastPurchase: '2026-01-05' },
    { id: 6, name: 'Shampoo', category: 'Personal', lastPrice: 680, frequency: 60, lastPurchase: '2025-12-15' },
];

export default function Products() {
    const [products] = useState(mockProducts);
    const [filter, setFilter] = useState('all');

    const categories = ['all', ...new Set(products.map(p => p.category))];
    const filtered = filter === 'all' ? products : products.filter(p => p.category === filter);

    const totalMonthlySpend = products.reduce((sum, p) => sum + (p.lastPrice * (30 / p.frequency)), 0);

    return (
        <div className="h-full flex flex-col p-4">
            {/* Header */}
            <div className="flex justify-between items-center mb-4 flex-shrink-0">
                <div>
                    <h1 className="text-lg font-semibold">Product Inventory</h1>
                    <p className="text-xs text-slate-500">Track recurring purchases and unit economics</p>
                </div>
                <button className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 flex items-center gap-1 text-xs">
                    <Plus size={14} /> Add Product
                </button>
            </div>

            {/* Summary & Filter */}
            <div className="flex justify-between items-center mb-4 flex-shrink-0">
                <div className="flex gap-1">
                    {categories.map((cat) => (
                        <button
                            key={cat}
                            onClick={() => setFilter(cat)}
                            className={`px-2 py-1 text-xs ${filter === cat ? 'bg-slate-700 text-emerald-400' : 'text-slate-500 hover:text-slate-300'}`}
                        >
                            {cat === 'all' ? 'All' : cat}
                        </button>
                    ))}
                </div>
                <div className="text-xs text-slate-400">
                    Est. Monthly Spend: <span className="font-mono-nums text-amber-400">¥{Math.round(totalMonthlySpend).toLocaleString()}</span>
                </div>
            </div>

            {/* Products Table */}
            <div className="border border-slate-800 flex-1 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900 sticky top-0">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Product</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Category</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Last Price</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Freq (days)</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Monthly Cost</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Last Purchase</th>
                            <th className="p-2 w-16"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((p) => {
                            const monthlyCost = Math.round(p.lastPrice * (30 / p.frequency));
                            return (
                                <tr key={p.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                    <td className="p-2 flex items-center gap-2">
                                        <Package size={12} className="text-cyan-400" />
                                        {p.name}
                                    </td>
                                    <td className="p-2 text-slate-400">{p.category}</td>
                                    <td className="p-2 text-right font-mono-nums">¥{p.lastPrice.toLocaleString()}</td>
                                    <td className="p-2 text-right font-mono-nums text-slate-400">{p.frequency}</td>
                                    <td className="p-2 text-right font-mono-nums text-amber-400">¥{monthlyCost.toLocaleString()}</td>
                                    <td className="p-2 text-slate-500">{p.lastPurchase}</td>
                                    <td className="p-2">
                                        <div className="flex gap-1 justify-end">
                                            <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-slate-300">
                                                <Edit size={12} />
                                            </button>
                                            <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-rose-400">
                                                <Trash2 size={12} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
