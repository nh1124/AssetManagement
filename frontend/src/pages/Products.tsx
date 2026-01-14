import { useState, useMemo } from 'react';
import { Plus, Trash2, Edit, Package, Search, MapPin, TrendingDown } from 'lucide-react';

interface Product {
    id: number;
    name: string;
    category: string;
    location: string;
    lastPrice: number;
    frequency: number;
    lastPurchase: string;
    isAsset: boolean;
    lifespanMonths?: number;
}

const mockProducts: Product[] = [
    { id: 1, name: 'Milk', category: 'Groceries', location: 'LIFE Supermarket', lastPrice: 198, frequency: 7, lastPurchase: '2026-01-10', isAsset: false },
    { id: 2, name: 'Detergent', category: 'Household', location: 'Donki', lastPrice: 498, frequency: 30, lastPurchase: '2026-01-01', isAsset: false },
    { id: 3, name: 'Rice 5kg', category: 'Groceries', location: 'LIFE Supermarket', lastPrice: 1980, frequency: 45, lastPurchase: '2025-12-20', isAsset: false },
    { id: 4, name: 'Eggs (10)', category: 'Groceries', location: 'LIFE Supermarket', lastPrice: 298, frequency: 10, lastPurchase: '2026-01-08', isAsset: false },
    { id: 5, name: 'Coffee Beans', category: 'Groceries', location: 'Kaldi', lastPrice: 1280, frequency: 21, lastPurchase: '2026-01-05', isAsset: false },
    { id: 6, name: 'Shampoo', category: 'Personal', location: 'Matsumoto Kiyoshi', lastPrice: 680, frequency: 60, lastPurchase: '2025-12-15', isAsset: false },
    { id: 7, name: 'MacBook Pro', category: 'Electronics', location: 'Apple Store', lastPrice: 298000, frequency: 0, lastPurchase: '2024-06-15', isAsset: true, lifespanMonths: 48 },
    { id: 8, name: 'Office Chair', category: 'Furniture', location: 'IKEA', lastPrice: 45000, frequency: 0, lastPurchase: '2023-11-20', isAsset: true, lifespanMonths: 60 },
];

const categories = ['All', 'Groceries', 'Household', 'Personal', 'Electronics', 'Furniture'];

export default function Products() {
    const [products] = useState(mockProducts);
    const [filter, setFilter] = useState('All');
    const [searchTerm, setSearchTerm] = useState('');
    const [showCategoryDropdown, setShowCategoryDropdown] = useState(false);

    const filteredCategories = categories.filter(c =>
        c.toLowerCase().includes(searchTerm.toLowerCase())
    );

    const filtered = useMemo(() => {
        return products.filter(p => {
            const matchCategory = filter === 'All' || p.category === filter;
            const matchSearch = p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                p.location.toLowerCase().includes(searchTerm.toLowerCase());
            return matchCategory && (searchTerm === '' || matchSearch || filteredCategories.includes(p.category));
        });
    }, [products, filter, searchTerm, filteredCategories]);

    const totalMonthlySpend = products
        .filter(p => p.frequency > 0)
        .reduce((sum, p) => sum + (p.lastPrice * (30 / p.frequency)), 0);

    const calculateDepreciation = (product: Product) => {
        if (!product.isAsset || !product.lifespanMonths || product.lastPrice < 30000) return null;
        const dailyDepreciation = product.lastPrice / (product.lifespanMonths * 30);
        const daysSincePurchase = Math.floor((new Date().getTime() - new Date(product.lastPurchase).getTime()) / (1000 * 60 * 60 * 24));
        const totalDepreciation = dailyDepreciation * daysSincePurchase;
        const currentValue = Math.max(0, product.lastPrice - totalDepreciation);
        return { currentValue, totalDepreciation, dailyRate: dailyDepreciation };
    };

    const assetProducts = products.filter(p => p.isAsset && p.lastPrice >= 30000);
    const totalAssetValue = assetProducts.reduce((sum, p) => {
        const dep = calculateDepreciation(p);
        return sum + (dep?.currentValue ?? p.lastPrice);
    }, 0);

    return (
        <div className="h-full flex flex-col p-4">
            {/* Header */}
            <div className="flex justify-between items-center mb-4 flex-shrink-0">
                <div>
                    <h1 className="text-lg font-semibold">Product Inventory</h1>
                    <p className="text-xs text-slate-500">Track recurring purchases and asset depreciation</p>
                </div>
                <button className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 flex items-center gap-1 text-xs">
                    <Plus size={14} /> Add Product
                </button>
            </div>

            {/* Summary & Filter */}
            <div className="flex justify-between items-center mb-4 flex-shrink-0 gap-4">
                {/* Searchable Category Dropdown */}
                <div className="relative">
                    <div className="flex items-center gap-2 bg-slate-800 border border-slate-700 px-2 py-1.5">
                        <Search size={14} className="text-slate-500" />
                        <input
                            type="text"
                            placeholder="Search category..."
                            value={searchTerm}
                            onChange={(e) => {
                                setSearchTerm(e.target.value);
                                setShowCategoryDropdown(true);
                            }}
                            onFocus={() => setShowCategoryDropdown(true)}
                            className="bg-transparent text-xs focus:outline-none w-32"
                        />
                    </div>
                    {showCategoryDropdown && (
                        <div className="absolute top-full left-0 mt-1 bg-slate-800 border border-slate-700 z-10 min-w-full">
                            {filteredCategories.map((cat) => (
                                <button
                                    key={cat}
                                    onClick={() => {
                                        setFilter(cat);
                                        setSearchTerm('');
                                        setShowCategoryDropdown(false);
                                    }}
                                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-slate-700 ${filter === cat ? 'text-emerald-400' : 'text-slate-300'}`}
                                >
                                    {cat}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                <div className="flex gap-4 text-xs text-slate-400">
                    <span>Monthly Spend: <span className="font-mono-nums text-amber-400">¥{Math.round(totalMonthlySpend).toLocaleString()}</span></span>
                    <span>Asset Value: <span className="font-mono-nums text-emerald-400">¥{Math.round(totalAssetValue).toLocaleString()}</span></span>
                </div>
            </div>

            {/* Click outside to close dropdown */}
            {showCategoryDropdown && (
                <div className="fixed inset-0 z-5" onClick={() => setShowCategoryDropdown(false)} />
            )}

            {/* Products Table */}
            <div className="border border-slate-800 flex-1 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900 sticky top-0">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Product</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Category</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Location</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Price</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Value/Cost</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Last Purchase</th>
                            <th className="p-2 w-16"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((p) => {
                            const dep = calculateDepreciation(p);
                            const monthlyCost = p.frequency > 0 ? Math.round(p.lastPrice * (30 / p.frequency)) : null;

                            return (
                                <tr key={p.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                    <td className="p-2 flex items-center gap-2">
                                        <Package size={12} className={p.isAsset ? 'text-emerald-400' : 'text-cyan-400'} />
                                        <span>{p.name}</span>
                                        {p.isAsset && <span className="text-[9px] bg-emerald-900/50 text-emerald-400 px-1">ASSET</span>}
                                    </td>
                                    <td className="p-2 text-slate-400">{p.category}</td>
                                    <td className="p-2 text-slate-400 flex items-center gap-1">
                                        <MapPin size={10} className="text-slate-600" />
                                        {p.location}
                                    </td>
                                    <td className="p-2 text-right font-mono-nums">¥{p.lastPrice.toLocaleString()}</td>
                                    <td className="p-2 text-right">
                                        {dep ? (
                                            <div>
                                                <span className="font-mono-nums text-emerald-400">¥{Math.round(dep.currentValue).toLocaleString()}</span>
                                                <div className="flex items-center justify-end gap-1 text-[10px] text-rose-400">
                                                    <TrendingDown size={10} />
                                                    ¥{Math.round(dep.dailyRate).toLocaleString()}/day
                                                </div>
                                            </div>
                                        ) : monthlyCost ? (
                                            <span className="font-mono-nums text-amber-400">¥{monthlyCost.toLocaleString()}/mo</span>
                                        ) : (
                                            <span className="text-slate-600">-</span>
                                        )}
                                    </td>
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
