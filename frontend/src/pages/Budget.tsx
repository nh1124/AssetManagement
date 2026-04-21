import { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { MonthlyBudget } from '../types';
import { createBudget, deleteBudget, getBudgetDefaults, getBudgets } from '../api';
import { useToast } from '../components/Toast';

export default function Budget() {
    const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
    const [budgets, setBudgets] = useState<MonthlyBudget[]>([]);
    const [defaults, setDefaults] = useState<Array<{ account_id: number; account_name: string; budget_limit?: number }>>([]);
    const [newBudget, setNewBudget] = useState({ account_id: '', amount: '' });
    const [loading, setLoading] = useState(false);
    const { showToast } = useToast();

    const fetchData = async () => {
        setLoading(true);
        try {
            const [budgetRows, defaultRows] = await Promise.all([
                getBudgets(period),
                getBudgetDefaults(),
            ]);
            setBudgets(budgetRows);
            setDefaults(defaultRows);
        } catch (error) {
            console.error(error);
            showToast('Failed to load budget data', 'error');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, [period]);

    const totalPlanned = useMemo(
        () => budgets.reduce((sum, b) => sum + b.amount, 0),
        [budgets]
    );
    const totalActual = useMemo(
        () => budgets.reduce((sum, b) => sum + b.actual_spending, 0),
        [budgets]
    );
    const variance = totalPlanned - totalActual;

    const handleUpsert = async () => {
        if (!newBudget.account_id || !newBudget.amount) return;
        try {
            await createBudget({
                account_id: parseInt(newBudget.account_id, 10),
                target_period: period,
                amount: parseFloat(newBudget.amount),
            });
            setNewBudget({ account_id: '', amount: '' });
            showToast('Budget saved', 'success');
            fetchData();
        } catch (error) {
            console.error(error);
            showToast('Failed to save budget', 'error');
        }
    };

    const handleDelete = async (id: string) => {
        try {
            await deleteBudget(id);
            showToast('Budget deleted', 'info');
            fetchData();
        } catch (error) {
            console.error(error);
            showToast('Failed to delete budget', 'error');
        }
    };

    return (
        <div className="h-full flex flex-col p-4 gap-4">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-lg font-semibold">Budget Management</h1>
                    <p className="text-xs text-slate-500">Monthly budgets by expense account</p>
                </div>
                <input
                    type="month"
                    value={period}
                    onChange={(e) => setPeriod(e.target.value)}
                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                />
            </div>

            <div className="grid grid-cols-3 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Planned</p>
                    <p className="text-xl font-bold font-mono-nums text-slate-200">¥{Math.round(totalPlanned).toLocaleString()}</p>
                </div>
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Actual</p>
                    <p className="text-xl font-bold font-mono-nums text-amber-400">¥{Math.round(totalActual).toLocaleString()}</p>
                </div>
                <div className="p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Variance</p>
                    <p className={`text-xl font-bold font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {variance >= 0 ? '+' : ''}¥{Math.round(variance).toLocaleString()}
                    </p>
                </div>
            </div>

            <div className="border border-slate-800 p-3 grid grid-cols-4 gap-2 items-end">
                <div className="col-span-2">
                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Expense Account</label>
                    <select
                        value={newBudget.account_id}
                        onChange={(e) => setNewBudget({ ...newBudget, account_id: e.target.value })}
                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                    >
                        <option value="">Select...</option>
                        {defaults.map((row) => (
                            <option key={row.account_id} value={row.account_id}>
                                {row.account_name}
                            </option>
                        ))}
                    </select>
                </div>
                <div>
                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Amount</label>
                    <input
                        type="number"
                        value={newBudget.amount}
                        onChange={(e) => setNewBudget({ ...newBudget, amount: e.target.value })}
                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                    />
                </div>
                <button
                    onClick={handleUpsert}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 flex items-center justify-center gap-1 text-xs"
                >
                    <Plus size={14} /> Upsert
                </button>
            </div>

            <div className="border border-slate-800 flex-1 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900 sticky top-0">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Account</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Budget</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Actual</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Variance</th>
                            <th className="p-2 w-16"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td className="p-3 text-slate-500" colSpan={5}>Loading...</td></tr>
                        ) : budgets.length === 0 ? (
                            <tr><td className="p-3 text-slate-500" colSpan={5}>No monthly budgets for this period.</td></tr>
                        ) : (
                            budgets.map((b) => (
                                <tr key={b.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                    <td className="p-2">{b.account_name}</td>
                                    <td className="p-2 text-right font-mono-nums text-slate-300">¥{Math.round(b.amount).toLocaleString()}</td>
                                    <td className="p-2 text-right font-mono-nums text-amber-400">¥{Math.round(b.actual_spending).toLocaleString()}</td>
                                    <td className={`p-2 text-right font-mono-nums ${b.variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {b.variance >= 0 ? '+' : ''}¥{Math.round(b.variance).toLocaleString()}
                                    </td>
                                    <td className="p-2 text-right">
                                        <button onClick={() => handleDelete(b.id)} className="p-1 hover:bg-slate-700 text-slate-500 hover:text-rose-400">
                                            <Trash2 size={12} />
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
