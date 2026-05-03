import { useEffect, useState } from 'react';
import { Archive, ChevronLeft, ChevronRight, Copy, Edit2, Plus, Save, Sparkles, Trash2 } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import { useToast } from '../components/Toast';
import { useClient } from '../context/ClientContext';
import {
    createAccount,
    createCapsule,
    deleteCapsule,
    getBudgetSummary,
    getCapsules,
    processCapsuleContributions,
    saveMonthlyBudgets,
    suggestBudget,
    updateAccount,
    updateCapsule,
} from '../api';
import { formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import type { Capsule } from '../types';

interface BudgetAccount {
    id: number;
    name: string;
    amount: number;
    balance: number;
    is_custom: boolean;
}

interface BudgetSummary {
    period: string;
    required_monthly_savings: number;
    monthly_fixed_costs: number;
    monthly_income: number;
    total_variable_budget: number;
    remaining_balance: number;
    expense_accounts: BudgetAccount[];
    goals_count: number;
    total_goal_gap: number;
}

const TABS = [
    { id: 'budgeting', label: 'Budgeting' },
    { id: 'capsules', label: 'Capsules' },
];

export default function Strategy() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [activeTab, setActiveTab] = useState('budgeting');
    const [currentPeriod, setCurrentPeriod] = useState(new Date().toISOString().slice(0, 7));
    const [budgetSummary, setBudgetSummary] = useState<BudgetSummary | null>(null);
    const [budgetEdits, setBudgetEdits] = useState<Record<number, number>>({});
    const [showBudgetCategoryForm, setShowBudgetCategoryForm] = useState(false);
    const [editingBudgetAccount, setEditingBudgetAccount] = useState<BudgetAccount | null>(null);
    const [budgetCategoryForm, setBudgetCategoryForm] = useState({ name: '', amount: '' });
    const [budgetThinking, setBudgetThinking] = useState(false);

    const [capsules, setCapsules] = useState<Capsule[]>([]);
    const [showCapsuleForm, setShowCapsuleForm] = useState(false);
    const [editingCapsuleId, setEditingCapsuleId] = useState<number | null>(null);
    const [capsuleForm, setCapsuleForm] = useState({ name: '', target_amount: '', monthly_contribution: '', current_balance: '0' });

    const variableBudgetTotal = Object.values(budgetEdits).reduce((sum, amount) => sum + amount, 0);
    const calculatedRemaining = (budgetSummary?.monthly_income || 0)
        - (budgetSummary?.required_monthly_savings || 0)
        - (budgetSummary?.monthly_fixed_costs || 0)
        - variableBudgetTotal;
    const formatCurrency = (value: number | undefined | null) =>
        formatCurrencyWithSetting(value, currentClient?.general_settings?.currency);

    const fetchBudgetSummary = async (period = currentPeriod) => {
        try {
            const summary = await getBudgetSummary(period);
            const edits: Record<number, number> = {};
            summary.expense_accounts.forEach((account: BudgetAccount) => {
                edits[account.id] = account.amount;
            });
            setBudgetSummary(summary);
            setBudgetEdits(edits);
        } catch (error) {
            console.error('Failed to fetch budget summary:', error);
            showToast('Failed to load budget summary', 'error');
        }
    };

    const fetchCapsules = async () => {
        try {
            setCapsules(await getCapsules());
        } catch (error) {
            console.error('Failed to fetch capsules:', error);
            showToast('Failed to load capsules', 'error');
        }
    };

    useEffect(() => {
        if (activeTab === 'budgeting') fetchBudgetSummary();
        if (activeTab === 'capsules') fetchCapsules();
    }, [activeTab, currentPeriod]);

    const changePeriod = (delta: number) => {
        const [year, month] = currentPeriod.split('-').map(Number);
        const date = new Date(year, month - 1 + delta, 1);
        setCurrentPeriod(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`);
    };

    const copyPreviousBudget = async () => {
        const [year, month] = currentPeriod.split('-').map(Number);
        const previousDate = new Date(year, month - 2, 1);
        const previousPeriod = `${previousDate.getFullYear()}-${String(previousDate.getMonth() + 1).padStart(2, '0')}`;
        try {
            const previousSummary = await getBudgetSummary(previousPeriod);
            const edits: Record<number, number> = {};
            previousSummary.expense_accounts.forEach((account: BudgetAccount) => {
                edits[account.id] = account.amount;
            });
            setBudgetEdits(edits);
            showToast(`Copied from ${previousPeriod}`, 'info');
        } catch (error) {
            showToast('Failed to copy previous budget', 'error');
        }
    };

    const saveBudget = async () => {
        try {
            await saveMonthlyBudgets(Object.entries(budgetEdits).map(([accountId, amount]) => ({
                account_id: Number(accountId),
                target_period: currentPeriod,
                amount,
            })));
            showToast('Monthly budget saved', 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to save budget', 'error');
        }
    };

    const applyBudgetSuggestions = async () => {
        if (!budgetSummary) return;
        setBudgetThinking(true);
        try {
            const suggestions = await suggestBudget();
            const edits = { ...budgetEdits };
            let applied = 0;
            suggestions.forEach((suggestion: any) => {
                const account = budgetSummary.expense_accounts.find(
                    (item) => item.name.toLowerCase().includes(suggestion.category.toLowerCase())
                        || suggestion.category.toLowerCase().includes(item.name.toLowerCase()),
                );
                if (account) {
                    edits[account.id] = suggestion.suggested_limit;
                    applied += 1;
                }
            });
            setBudgetEdits(edits);
            showToast(applied > 0 ? `Applied ${applied} budget suggestions` : 'No matching categories found', applied > 0 ? 'success' : 'info');
        } catch (error) {
            showToast('Failed to get budget suggestions', 'error');
        } finally {
            setBudgetThinking(false);
        }
    };

    const openBudgetCategoryForm = (account?: BudgetAccount) => {
        setEditingBudgetAccount(account ?? null);
        setBudgetCategoryForm(account
            ? { name: account.name, amount: String(budgetEdits[account.id] ?? account.amount ?? 0) }
            : { name: '', amount: '' });
        setShowBudgetCategoryForm(true);
    };

    const saveBudgetCategory = async () => {
        const name = budgetCategoryForm.name.trim();
        if (!name) return;
        const amount = Number(budgetCategoryForm.amount || '0') || 0;
        try {
            if (editingBudgetAccount) {
                await updateAccount(editingBudgetAccount.id, { name });
                await saveMonthlyBudgets([{ account_id: editingBudgetAccount.id, target_period: currentPeriod, amount }]);
                showToast('Budget category updated', 'success');
            } else {
                const created = await createAccount({ name, account_type: 'expense', balance: 0 });
                await saveMonthlyBudgets([{ account_id: created.id, target_period: currentPeriod, amount }]);
                showToast('Budget category added', 'success');
            }
            setShowBudgetCategoryForm(false);
            setEditingBudgetAccount(null);
            setBudgetCategoryForm({ name: '', amount: '' });
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to save budget category', 'error');
        }
    };

    const openCapsuleForm = (capsule?: Capsule) => {
        setEditingCapsuleId(capsule?.id ?? null);
        setCapsuleForm(capsule
            ? {
                name: capsule.name,
                target_amount: String(capsule.target_amount),
                monthly_contribution: String(capsule.monthly_contribution),
                current_balance: '0',
            }
            : { name: '', target_amount: '', monthly_contribution: '', current_balance: '0' });
        setShowCapsuleForm(true);
    };

    const saveCapsule = async () => {
        if (!capsuleForm.name || !capsuleForm.target_amount) return;
        const payload = {
            name: capsuleForm.name,
            target_amount: Number(capsuleForm.target_amount),
            monthly_contribution: Number(capsuleForm.monthly_contribution || '0'),
        };
        try {
            if (editingCapsuleId) await updateCapsule(editingCapsuleId, payload);
            else await createCapsule(payload);
            setShowCapsuleForm(false);
            showToast('Capsule saved', 'success');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to save capsule', 'error');
        }
    };

    const removeCapsule = async (id: number) => {
        if (!confirm('Delete this capsule?')) return;
        try {
            await deleteCapsule(id);
            showToast('Capsule deleted', 'info');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to delete capsule', 'error');
        }
    };

    const processCapsules = async () => {
        if (!confirm('Process monthly contributions for all capsules?')) return;
        try {
            const result = await processCapsuleContributions();
            showToast(result.message, 'success');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to process contributions', 'error');
        }
    };

    const renderBudgeting = () => (
        <div className="grid grid-cols-1 min-[960px]:grid-cols-[380px_1fr] gap-4 p-4">
            <section className="space-y-4">
                <div className="bg-slate-900/60 border border-slate-800 p-4">
                    <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3">Monthly Frame</h2>
                    <div className="flex items-center justify-between bg-slate-800/40 border border-slate-700 px-3 py-2 mb-3">
                        <button onClick={() => changePeriod(-1)} className="p-1 hover:bg-slate-700 text-slate-400"><ChevronLeft size={16} /></button>
                        <span className="text-sm font-medium font-mono-nums">{currentPeriod}</span>
                        <button onClick={() => changePeriod(1)} className="p-1 hover:bg-slate-700 text-slate-400"><ChevronRight size={16} /></button>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Income</p><p className="font-mono-nums text-emerald-400">{formatCurrency(budgetSummary?.monthly_income)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Goal Savings</p><p className="font-mono-nums text-cyan-400">{formatCurrency(budgetSummary?.required_monthly_savings)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Fixed Costs</p><p className="font-mono-nums text-amber-400">{formatCurrency(budgetSummary?.monthly_fixed_costs)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Remaining</p><p className={`font-mono-nums ${calculatedRemaining >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(calculatedRemaining)}</p></div>
                    </div>
                </div>

                <div className="bg-slate-900/60 border border-slate-800 p-4 space-y-2">
                    <h2 className="text-xs text-slate-400 uppercase tracking-wider">Actions</h2>
                    <button onClick={copyPreviousBudget} className="w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 py-2 text-xs text-slate-300 flex items-center justify-center gap-2"><Copy size={14} /> Copy Previous Month</button>
                    <button onClick={applyBudgetSuggestions} disabled={budgetThinking} className="w-full bg-purple-900/40 hover:bg-purple-900/60 border border-purple-800 py-2 text-xs text-purple-200 flex items-center justify-center gap-2 disabled:opacity-50"><Sparkles size={14} /> {budgetThinking ? 'Thinking...' : 'AI Suggest Budget'}</button>
                    <button onClick={() => openBudgetCategoryForm()} className="w-full bg-emerald-900/40 hover:bg-emerald-900/60 border border-emerald-800 py-2 text-xs text-emerald-200 flex items-center justify-center gap-2"><Plus size={14} /> Add Category</button>
                    <button onClick={saveBudget} className="w-full bg-cyan-600 hover:bg-cyan-500 py-2 text-xs text-white flex items-center justify-center gap-2"><Save size={14} /> Save {currentPeriod}</button>
                </div>
            </section>

            <section className="bg-slate-900/60 border border-slate-800 p-4 overflow-auto">
                <div className="flex items-center justify-between mb-3">
                    <h2 className="text-xs text-slate-400 uppercase tracking-wider">Variable Budget</h2>
                    <span className="text-xs text-slate-500 font-mono-nums">Total {formatCurrency(variableBudgetTotal)}</span>
                </div>

                {showBudgetCategoryForm && (
                    <div className="mb-3 border border-emerald-800/40 bg-emerald-900/10 p-3 grid grid-cols-12 gap-2 items-end">
                        <input value={budgetCategoryForm.name} onChange={(event) => setBudgetCategoryForm({ ...budgetCategoryForm, name: event.target.value })} placeholder="Category" className="col-span-5 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                        <input type="number" value={budgetCategoryForm.amount} onChange={(event) => setBudgetCategoryForm({ ...budgetCategoryForm, amount: event.target.value })} placeholder="Amount" className="col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                        <button onClick={saveBudgetCategory} className="col-span-2 bg-emerald-600 hover:bg-emerald-500 text-white py-1.5 text-xs">{editingBudgetAccount ? 'Update' : 'Add'}</button>
                        <button onClick={() => setShowBudgetCategoryForm(false)} className="col-span-2 bg-slate-800 hover:bg-slate-700 text-slate-300 py-1.5 text-xs">Cancel</button>
                    </div>
                )}

                <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                        <thead className="text-slate-500 uppercase border-b border-slate-700 bg-slate-800/50">
                            <tr>
                                <th className="px-2 py-2 text-left font-normal">Category</th>
                                <th className="px-2 py-2 text-right font-normal">Actual</th>
                                <th className="px-2 py-2 text-right font-normal">Budget</th>
                                <th className="px-2 py-2 text-right font-normal">Variance</th>
                                <th className="px-2 py-2 text-right font-normal">Edit</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/70">
                            {(budgetSummary?.expense_accounts ?? []).map((account) => {
                                const limit = budgetEdits[account.id] ?? 0;
                                const variance = limit - (account.balance || 0);
                                return (
                                    <tr key={account.id} className="hover:bg-slate-800/30 group">
                                        <td className="px-2 py-2 text-slate-300">{account.name}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-slate-500">{formatCurrency(account.balance)}</td>
                                        <td className="px-2 py-2 text-right"><input type="number" step="1000" value={limit} onChange={(event) => setBudgetEdits({ ...budgetEdits, [account.id]: Number(event.target.value) || 0 })} className="w-24 bg-transparent border-b border-slate-700 focus:border-cyan-500 text-right font-mono-nums outline-none" /></td>
                                        <td className={`px-2 py-2 text-right font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(variance)}</td>
                                        <td className="px-2 py-2 text-right"><button onClick={() => openBudgetCategoryForm(account)} className="text-slate-500 hover:text-cyan-400 opacity-0 group-hover:opacity-100"><Edit2 size={12} /></button></td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    );

    const renderCapsules = () => (
        <div className="grid grid-cols-1 min-[960px]:grid-cols-[340px_1fr] gap-4 p-4">
            <section className="bg-slate-900/60 border border-slate-800 p-4 space-y-3">
                <h2 className="text-xs text-slate-400 uppercase tracking-wider">Capsule Actions</h2>
                <button onClick={() => openCapsuleForm()} className="w-full bg-purple-900/40 hover:bg-purple-900/60 border border-purple-800 py-2 text-xs text-purple-200 flex items-center justify-center gap-2"><Plus size={14} /> New Capsule</button>
                <button onClick={processCapsules} className="w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 py-2 text-xs text-slate-300 flex items-center justify-center gap-2"><Sparkles size={14} /> Process Contributions</button>
                {showCapsuleForm && (
                    <div className="border border-purple-800/50 bg-purple-900/10 p-3 space-y-2">
                        <input value={capsuleForm.name} onChange={(event) => setCapsuleForm({ ...capsuleForm, name: event.target.value })} placeholder="Name" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                        <input type="number" value={capsuleForm.target_amount} onChange={(event) => setCapsuleForm({ ...capsuleForm, target_amount: event.target.value })} placeholder="Target amount" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                        <input type="number" value={capsuleForm.monthly_contribution} onChange={(event) => setCapsuleForm({ ...capsuleForm, monthly_contribution: event.target.value })} placeholder="Monthly contribution" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                        <div className="flex gap-2"><button onClick={saveCapsule} className="flex-1 bg-purple-600 hover:bg-purple-500 text-white py-2 text-xs">Save</button><button onClick={() => setShowCapsuleForm(false)} className="px-3 bg-slate-800 text-slate-400 text-xs">Cancel</button></div>
                    </div>
                )}
            </section>

            <section className="bg-slate-900/60 border border-slate-800 p-4 overflow-auto">
                <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3">Sinking Funds</h2>
                <div className="grid grid-cols-1 min-[1120px]:grid-cols-2 gap-3">
                    {capsules.length === 0 ? <p className="text-xs text-slate-600">No capsules yet.</p> : capsules.map((capsule) => {
                        const progress = capsule.target_amount > 0 ? Math.min(100, (capsule.current_balance / capsule.target_amount) * 100) : 0;
                        return (
                            <div key={capsule.id} className="bg-slate-800/30 border border-slate-700 p-3 space-y-3">
                                <div className="flex justify-between gap-3">
                                    <div><p className="text-sm text-slate-100 flex items-center gap-2"><Archive size={14} className="text-purple-400" /> {capsule.name}</p><p className="text-[10px] text-slate-500">Target {formatCurrency(capsule.target_amount)}</p></div>
                                    <div className="text-right"><p className="text-lg font-mono-nums text-purple-400">{formatCurrency(capsule.current_balance)}</p><p className="text-[10px] text-slate-500">+{formatCurrency(capsule.monthly_contribution)} / mo</p></div>
                                </div>
                                <div className="h-1.5 bg-slate-900 rounded-full overflow-hidden"><div className="h-full bg-purple-500" style={{ width: `${progress}%` }} /></div>
                                <div className="flex justify-end gap-3 text-[10px]"><button onClick={() => openCapsuleForm(capsule)} className="text-slate-400 hover:text-white flex items-center gap-1"><Edit2 size={10} /> Edit</button><button onClick={() => removeCapsule(capsule.id)} className="text-slate-400 hover:text-rose-400 flex items-center gap-1"><Trash2 size={10} /> Delete</button></div>
                            </div>
                        );
                    })}
                </div>
            </section>
        </div>
    );

    return (
        <div className="h-full flex flex-col">
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                {activeTab === 'budgeting' && renderBudgeting()}
                {activeTab === 'capsules' && renderCapsules()}
            </TabPanel>
        </div>
    );
}
