import { useEffect, useMemo, useState } from 'react';
import { Package, RefreshCw } from 'lucide-react';
import type { Product } from '../types';
import { getProducts, getUnitEconomicsSummary } from '../api';

export default function Products() {
    const [products, setProducts] = useState<Product[]>([]);
    const [summary, setSummary] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [productRows, summaryRows] = await Promise.all([
                getProducts(),
                getUnitEconomicsSummary(),
            ]);
            setProducts(productRows);
            setSummary(summaryRows);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    const consumables = useMemo(
        () => products.filter((p) => !p.is_asset),
        [products]
    );
    const assets = useMemo(
        () => products.filter((p) => p.is_asset),
        [products]
    );

    return (
        <div className="h-full flex flex-col p-4 gap-4">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-lg font-semibold">Product Inventory</h1>
                    <p className="text-xs text-slate-500">Unit economics and replenishment tracking</p>
                </div>
                <button
                    onClick={fetchData}
                    className="p-2 border border-slate-700 hover:bg-slate-800 text-slate-400"
                >
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div className="grid grid-cols-3 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Total Products</p>
                    <p className="text-xl font-bold font-mono-nums text-slate-200">{products.length}</p>
                </div>
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Monthly Consumable Cost</p>
                    <p className="text-xl font-bold font-mono-nums text-amber-400">¥{Math.round(summary?.total_monthly_cost ?? 0).toLocaleString()}</p>
                </div>
                <div className="p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Asset / Consumable</p>
                    <p className="text-xl font-bold font-mono-nums text-emerald-400">
                        {assets.length} / <span className="text-cyan-400">{consumables.length}</span>
                    </p>
                </div>
            </div>

            <div className="border border-slate-800 flex-1 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900 sticky top-0">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Product</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Category</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Unit Price</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Unit Cost</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Monthly Cost</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Next Purchase</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td className="p-3 text-slate-500" colSpan={6}>Loading...</td></tr>
                        ) : products.length === 0 ? (
                            <tr><td className="p-3 text-slate-500" colSpan={6}>No products found.</td></tr>
                        ) : (
                            products.map((p) => (
                                <tr key={p.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                    <td className="p-2 flex items-center gap-2">
                                        <Package size={12} className={p.is_asset ? 'text-emerald-400' : 'text-cyan-400'} />
                                        {p.name}
                                    </td>
                                    <td className="p-2 text-slate-400">{p.category}</td>
                                    <td className="p-2 text-right font-mono-nums">¥{p.last_unit_price.toLocaleString()}</td>
                                    <td className="p-2 text-right font-mono-nums text-amber-400">¥{p.unit_cost.toLocaleString()}</td>
                                    <td className="p-2 text-right font-mono-nums text-cyan-400">
                                        {p.is_asset ? '-' : `¥${Math.round(p.monthly_cost).toLocaleString()}`}
                                    </td>
                                    <td className="p-2 text-slate-500">{p.next_purchase_date ?? '-'}</td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            <div className="border border-slate-800 p-3">
                <p className="text-[10px] text-slate-500 uppercase mb-2">Top Categories (Consumables)</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {(summary?.category_breakdown ?? []).slice(0, 3).map((row: any) => (
                        <div key={row.category} className="bg-slate-900/60 border border-slate-700 p-2">
                            <p className="text-xs text-slate-300">{row.category}</p>
                            <p className="text-sm font-mono-nums text-amber-400">¥{Math.round(row.monthly_cost).toLocaleString()} / mo</p>
                        </div>
                    ))}
                    {!summary?.category_breakdown?.length && (
                        <p className="text-xs text-slate-500">No consumable category data yet.</p>
                    )}
                </div>
            </div>
        </div>
    );
}
