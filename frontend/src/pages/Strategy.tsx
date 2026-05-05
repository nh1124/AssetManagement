import { useEffect, useState } from 'react';
import { Archive, ChevronLeft, ChevronRight, Copy, Edit2, Plus, Save, Sparkles, Trash2, X } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import { useToast } from '../components/Toast';
import { useClient } from '../context/ClientContext';
import {
    createAccount,
    createCapsule,
    createCapsuleHolding,
    createCapsuleRule,
    deleteCapsule,
    deleteCapsuleHolding,
    deleteCapsuleRule,
    getAccounts,
    getBudgetSummary,
    getCapsuleRules,
    getCapsules,
    processCapsuleContributions,
    saveMonthlyBudgets,
    suggestBudget,
    updateAccount,
    updateCapsule,
} from '../api';
import { formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import type { Account, Capsule, CapsuleRule, Transaction } from '../types';

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
    total_capsule_plan: number;
    total_capsule_actual: number;
    remaining_balance: number;
    expense_accounts: BudgetAccount[];
    sinking_funds: Array<{
        id: number;
        name: string;
        life_event_id?: number | null;
        account_id?: number | null;
        planned: number;
        actual: number;
        variance: number;
        current_balance: number;
        target_amount: number;
    }>;
    goals_count: number;
    total_goal_gap: number;
}

type TransactionKind = Transaction['type'];

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
    const [capsuleRules, setCapsuleRules] = useState<CapsuleRule[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [capsuleDeleteModal, setCapsuleDeleteModal] = useState<{
        capsuleId: number;
        capsuleName: string;
        currentBalance: number;
        transferAccountId: string;
        confirming: boolean;
    } | null>(null);
    const [showCapsuleForm, setShowCapsuleForm] = useState(false);
    const [showRuleForm, setShowRuleForm] = useState(false);
    const [editingCapsuleId, setEditingCapsuleId] = useState<number | null>(null);
    const [capsuleForm, setCapsuleForm] = useState({ name: '', target_amount: '', monthly_contribution: '', current_balance: '0' });
    const [ruleForm, setRuleForm] = useState({
        capsule_id: '',
        trigger_type: 'Income' as TransactionKind,
        trigger_category: '',
        trigger_description: '',
        source_mode: 'transaction_account',
        source_account_id: '',
        amount_type: 'fixed',
        amount_value: '',
    });
    const [expandedHoldingCapsules, setExpandedHoldingCapsules] = useState<Set<number>>(new Set());
    const [holdingForms, setHoldingForms] = useState<Record<number, { account_id: string; held_amount: string }>>({});

    const variableBudgetTotal = Object.values(budgetEdits).reduce((sum, amount) => sum + amount, 0);
    const calculatedRemaining = (budgetSummary?.monthly_income || 0)
        - (budgetSummary?.required_monthly_savings || 0)
        - (budgetSummary?.monthly_fixed_costs || 0)
        - variableBudgetTotal
        - (budgetSummary?.total_capsule_plan || 0);
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
            const [capsuleData, ruleData, accountData] = await Promise.all([
                getCapsules(),
                getCapsuleRules(),
                getAccounts(),
            ]);
            setCapsules(capsuleData);
            setCapsuleRules(ruleData);
            setAccounts(accountData);
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

    const openCapsuleDeleteModal = (capsule: Capsule) => {
        setCapsuleDeleteModal({
            capsuleId: capsule.id,
            capsuleName: capsule.name,
            currentBalance: capsule.current_balance ?? 0,
            transferAccountId: '',
            confirming: false,
        });
    };

    const confirmCapsuleDelete = async () => {
        if (!capsuleDeleteModal) return;
        const hasBalance = capsuleDeleteModal.currentBalance > 0;
        if (hasBalance && !capsuleDeleteModal.transferAccountId) {
            showToast('Please select a transfer account', 'warning');
            return;
        }
        setCapsuleDeleteModal({ ...capsuleDeleteModal, confirming: true });
        try {
            const transferId = capsuleDeleteModal.transferAccountId
                ? Number(capsuleDeleteModal.transferAccountId)
                : undefined;
            await deleteCapsule(capsuleDeleteModal.capsuleId, transferId);
            showToast('Capsule deleted', 'info');
            setCapsuleDeleteModal(null);
            await fetchCapsules();
        } catch (error) {
            const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            showToast(detail || 'Failed to delete capsule', 'error');
            setCapsuleDeleteModal({ ...capsuleDeleteModal, confirming: false });
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

    const toggleHoldings = (capsuleId: number) => {
        setExpandedHoldingCapsules((prev) => {
            const next = new Set(prev);
            if (next.has(capsuleId)) next.delete(capsuleId);
            else next.add(capsuleId);
            return next;
        });
    };

    const saveHolding = async (capsuleId: number) => {
        const form = holdingForms[capsuleId];
        if (!form?.account_id || !form?.held_amount) return;
        try {
            await createCapsuleHolding(capsuleId, {
                account_id: Number(form.account_id),
                held_amount: Number(form.held_amount),
            });
            setHoldingForms((prev) => ({ ...prev, [capsuleId]: { account_id: '', held_amount: '' } }));
            showToast('Holding saved', 'success');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to save holding', 'error');
        }
    };

    const removeHolding = async (capsuleId: number, holdingId: number) => {
        try {
            await deleteCapsuleHolding(capsuleId, holdingId);
            showToast('Holding removed', 'info');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to remove holding', 'error');
        }
    };

    const saveCapsuleRule = async () => {
        if (!ruleForm.capsule_id || !ruleForm.amount_value) return;
        try {
            await createCapsuleRule({
                capsule_id: Number(ruleForm.capsule_id),
                trigger_type: ruleForm.trigger_type,
                trigger_category: ruleForm.trigger_category.trim() || null,
                trigger_description: ruleForm.trigger_description.trim() || null,
                source_mode: ruleForm.source_mode,
                source_account_id: ruleForm.source_mode === 'fixed_account' && ruleForm.source_account_id ? Number(ruleForm.source_account_id) : null,
                amount_type: ruleForm.amount_type,
                amount_value: Number(ruleForm.amount_value),
                is_active: true,
            });
            setRuleForm({
                capsule_id: '',
                trigger_type: 'Income',
                trigger_category: '',
                trigger_description: '',
                source_mode: 'transaction_account',
                source_account_id: '',
                amount_type: 'fixed',
                amount_value: '',
            });
            setShowRuleForm(false);
            showToast('Capsule rule saved', 'success');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to save capsule rule', 'error');
        }
    };

    const removeCapsuleRule = async (id: number) => {
        if (!confirm('Delete this capsule rule?')) return;
        try {
            await deleteCapsuleRule(id);
            showToast('Capsule rule deleted', 'info');
            await fetchCapsules();
        } catch (error) {
            showToast('Failed to delete capsule rule', 'error');
        }
    };

    const renderBudgeting = () => {
        const variableActualTotal = (budgetSummary?.expense_accounts ?? []).reduce((sum, account) => sum + (account.balance || 0), 0);
        const variableVarianceTotal = variableBudgetTotal - variableActualTotal;
        const sinkingPlanTotal = budgetSummary?.total_capsule_plan ?? 0;
        const sinkingActualTotal = budgetSummary?.total_capsule_actual ?? 0;
        const sinkingVarianceTotal = sinkingPlanTotal - sinkingActualTotal;
        const sinkingBalanceTotal = (budgetSummary?.sinking_funds ?? []).reduce((sum, fund) => sum + (fund.current_balance || 0), 0);

        return (
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
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Sinking Funds</p><p className="font-mono-nums text-purple-300">{formatCurrency(budgetSummary?.total_capsule_plan)}</p></div>
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
                            <tr className="border-t border-slate-700 bg-slate-800/40">
                                <td className="px-2 py-2 text-slate-100 font-medium">Total</td>
                                <td className="px-2 py-2 text-right font-mono-nums text-slate-300">{formatCurrency(variableActualTotal)}</td>
                                <td className="px-2 py-2 text-right font-mono-nums text-slate-200">{formatCurrency(variableBudgetTotal)}</td>
                                <td className={`px-2 py-2 text-right font-mono-nums ${variableVarianceTotal >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{formatCurrency(variableVarianceTotal)}</td>
                                <td className="px-2 py-2" />
                            </tr>
                        </tbody>
                    </table>
                </div>

                <div className="mt-6">
                    <div className="flex items-center justify-between mb-3">
                        <h2 className="text-xs text-slate-400 uppercase tracking-wider">Sinking Funds</h2>
                        <span className="text-xs text-slate-500 font-mono-nums">Actual {formatCurrency(budgetSummary?.total_capsule_actual)}</span>
                    </div>
                    <div className="overflow-x-auto border border-slate-800">
                        <table className="w-full text-[10px]">
                            <thead className="text-slate-500 uppercase border-b border-slate-700 bg-slate-800/50">
                                <tr>
                                    <th className="px-2 py-2 text-left font-normal">Capsule</th>
                                    <th className="px-2 py-2 text-right font-normal">Actual</th>
                                    <th className="px-2 py-2 text-right font-normal">Plan</th>
                                    <th className="px-2 py-2 text-right font-normal">Variance</th>
                                    <th className="px-2 py-2 text-right font-normal">Balance</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/70">
                                {(budgetSummary?.sinking_funds ?? []).length === 0 ? (
                                    <tr><td colSpan={5} className="px-2 py-4 text-slate-600">No capsule sinking funds.</td></tr>
                                ) : (budgetSummary?.sinking_funds ?? []).map((fund) => (
                                    <tr key={fund.id} className="hover:bg-slate-800/30">
                                        <td className="px-2 py-2 text-slate-300">{fund.name}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-slate-400">{formatCurrency(fund.actual)}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-purple-300">{formatCurrency(fund.planned)}</td>
                                        <td className={`px-2 py-2 text-right font-mono-nums ${fund.variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(fund.variance)}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-slate-500">{formatCurrency(fund.current_balance)}</td>
                                    </tr>
                                ))}
                                <tr className="border-t border-slate-700 bg-slate-800/40">
                                    <td className="px-2 py-2 text-slate-100 font-medium">Total</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-slate-300">{formatCurrency(sinkingActualTotal)}</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-purple-200">{formatCurrency(sinkingPlanTotal)}</td>
                                    <td className={`px-2 py-2 text-right font-mono-nums ${sinkingVarianceTotal >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{formatCurrency(sinkingVarianceTotal)}</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-slate-300">{formatCurrency(sinkingBalanceTotal)}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </section>
        </div>
        );
    };

    const renderCapsules = () => (
        <div className="grid grid-cols-1 min-[960px]:grid-cols-[340px_1fr] gap-4 p-4">
            <section className="bg-slate-900/60 border border-slate-800 p-4 space-y-3">
                <h2 className="text-xs text-slate-400 uppercase tracking-wider">Capsule Actions</h2>
                <button onClick={() => openCapsuleForm()} className="w-full bg-purple-900/40 hover:bg-purple-900/60 border border-purple-800 py-2 text-xs text-purple-200 flex items-center justify-center gap-2"><Plus size={14} /> New Capsule</button>
                <button onClick={processCapsules} className="w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 py-2 text-xs text-slate-300 flex items-center justify-center gap-2"><Sparkles size={14} /> Process Contributions</button>
                <button onClick={() => setShowRuleForm(!showRuleForm)} className="w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 py-2 text-xs text-slate-300 flex items-center justify-center gap-2"><Plus size={14} /> Auto Rule</button>
                {showCapsuleForm && (
                    <div className="border border-purple-800/50 bg-purple-900/10 p-3 space-y-2">
                        <input value={capsuleForm.name} onChange={(event) => setCapsuleForm({ ...capsuleForm, name: event.target.value })} placeholder="Name" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                        <input type="number" value={capsuleForm.target_amount} onChange={(event) => setCapsuleForm({ ...capsuleForm, target_amount: event.target.value })} placeholder="Target amount" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                        <input type="number" value={capsuleForm.monthly_contribution} onChange={(event) => setCapsuleForm({ ...capsuleForm, monthly_contribution: event.target.value })} placeholder="Monthly contribution" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                        <div className="flex gap-2"><button onClick={saveCapsule} className="flex-1 bg-purple-600 hover:bg-purple-500 text-white py-2 text-xs">Save</button><button onClick={() => setShowCapsuleForm(false)} className="px-3 bg-slate-800 text-slate-400 text-xs">Cancel</button></div>
                    </div>
                )}
                {showRuleForm && (
                    <div className="border border-cyan-800/50 bg-cyan-900/10 p-3 space-y-2">
                        <select value={ruleForm.capsule_id} onChange={(event) => setRuleForm({ ...ruleForm, capsule_id: event.target.value })} className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                            <option value="">Capsule</option>
                            {capsules.map((capsule) => <option key={capsule.id} value={capsule.id}>{capsule.name}</option>)}
                        </select>
                        <div className="grid grid-cols-2 gap-2">
                            <select value={ruleForm.trigger_type} onChange={(event) => setRuleForm({ ...ruleForm, trigger_type: event.target.value as TransactionKind })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                {(['Income', 'Expense', 'CreditExpense', 'Transfer'] as TransactionKind[]).map((type) => <option key={type} value={type}>{type}</option>)}
                            </select>
                            <input value={ruleForm.trigger_category} onChange={(event) => setRuleForm({ ...ruleForm, trigger_category: event.target.value })} placeholder="Category contains" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                        </div>
                        <input value={ruleForm.trigger_description} onChange={(event) => setRuleForm({ ...ruleForm, trigger_description: event.target.value })} placeholder="Description contains" className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                        <div className="grid grid-cols-2 gap-2">
                            <select value={ruleForm.amount_type} onChange={(event) => setRuleForm({ ...ruleForm, amount_type: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="fixed">Fixed</option>
                                <option value="percentage">Percent</option>
                            </select>
                            <input type="number" value={ruleForm.amount_value} onChange={(event) => setRuleForm({ ...ruleForm, amount_value: event.target.value })} placeholder={ruleForm.amount_type === 'percentage' ? 'Percent' : 'Amount'} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                        </div>
                        <select value={ruleForm.source_mode} onChange={(event) => setRuleForm({ ...ruleForm, source_mode: event.target.value, source_account_id: '' })} className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                            <option value="transaction_account">Use transaction account</option>
                            <option value="fixed_account">Use fixed source account</option>
                        </select>
                        {ruleForm.source_mode === 'fixed_account' && (
                            <select value={ruleForm.source_account_id} onChange={(event) => setRuleForm({ ...ruleForm, source_account_id: event.target.value })} className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="">Source account</option>
                                {accounts.filter((account) => account.account_type === 'asset').map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                            </select>
                        )}
                        <div className="flex gap-2"><button onClick={saveCapsuleRule} className="flex-1 bg-cyan-700 hover:bg-cyan-600 text-white py-2 text-xs">Save Rule</button><button onClick={() => setShowRuleForm(false)} className="px-3 bg-slate-800 text-slate-400 text-xs">Cancel</button></div>
                    </div>
                )}
            </section>

            <section className="bg-slate-900/60 border border-slate-800 p-4 overflow-auto">
                <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3">Sinking Funds</h2>
                <div className="grid grid-cols-1 min-[1120px]:grid-cols-2 gap-3">
                    {capsules.length === 0 ? <p className="text-xs text-slate-600">No capsules yet.</p> : capsules.map((capsule) => {
                        const progress = capsule.target_amount > 0 ? Math.min(100, (capsule.current_balance / capsule.target_amount) * 100) : 0;
                        const holdingsExpanded = expandedHoldingCapsules.has(capsule.id);
                        const holdingForm = holdingForms[capsule.id] ?? { account_id: '', held_amount: '' };
                        const holdingsTotal = (capsule.holdings ?? []).reduce((s, h) => s + h.held_amount, 0);
                        return (
                            <div key={capsule.id} className="bg-slate-800/30 border border-slate-700 p-3 space-y-3">
                                <div className="flex justify-between gap-3">
                                    <div><p className="text-sm text-slate-100 flex items-center gap-2"><Archive size={14} className="text-purple-400" /> {capsule.name}</p><p className="text-[10px] text-slate-500">Target {formatCurrency(capsule.target_amount)}</p></div>
                                    <div className="text-right"><p className="text-lg font-mono-nums text-purple-400">{formatCurrency(capsule.current_balance)}</p><p className="text-[10px] text-slate-500">+{formatCurrency(capsule.monthly_contribution)} / mo</p></div>
                                </div>
                                <div className="h-1.5 bg-slate-900 rounded-full overflow-hidden"><div className="h-full bg-purple-500" style={{ width: `${progress}%` }} /></div>
                                <div>
                                    <button
                                        type="button"
                                        onClick={() => toggleHoldings(capsule.id)}
                                        className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 w-full"
                                    >
                                        <ChevronRight size={10} className={`transition-transform ${holdingsExpanded ? 'rotate-90' : ''}`} />
                                        <span>Holdings ({(capsule.holdings ?? []).length})</span>
                                        {(capsule.holdings ?? []).length > 0 && (
                                            <span className="ml-auto font-mono-nums">{formatCurrency(holdingsTotal)}</span>
                                        )}
                                    </button>
                                    {holdingsExpanded && (
                                        <div className="mt-2 space-y-1">
                                            {(capsule.holdings ?? []).length === 0 && (
                                                <p className="text-[10px] text-slate-600">No holdings recorded.</p>
                                            )}
                                            {(capsule.holdings ?? []).map((h) => (
                                                <div key={h.id} className="flex items-center gap-2 text-[10px]">
                                                    <span className="flex-1 text-slate-400 truncate">{h.account_name}</span>
                                                    <span className="font-mono-nums text-slate-300">{formatCurrency(h.held_amount)}</span>
                                                    <button type="button" title="Remove holding" onClick={() => removeHolding(capsule.id, h.id)} className="text-slate-600 hover:text-rose-400"><Trash2 size={10} /></button>
                                                </div>
                                            ))}
                                            <div className="flex gap-1.5 pt-2 border-t border-slate-800">
                                                <select
                                                    title="Select account"
                                                    value={holdingForm.account_id}
                                                    onChange={(e) => setHoldingForms((prev) => ({ ...prev, [capsule.id]: { ...prev[capsule.id], account_id: e.target.value } }))}
                                                    className="flex-1 bg-slate-900 border border-slate-700 px-1.5 py-1 text-[10px] text-slate-300"
                                                >
                                                    <option value="">Account...</option>
                                                    {accounts.filter((a) => a.account_type === 'asset').map((a) => (
                                                        <option key={a.id} value={a.id}>{a.name}</option>
                                                    ))}
                                                </select>
                                                <input
                                                    type="number"
                                                    placeholder="Amount"
                                                    value={holdingForm.held_amount}
                                                    onChange={(e) => setHoldingForms((prev) => ({ ...prev, [capsule.id]: { ...prev[capsule.id], held_amount: e.target.value } }))}
                                                    className="w-24 bg-slate-900 border border-slate-700 px-1.5 py-1 text-[10px] font-mono-nums"
                                                />
                                                <button type="button" onClick={() => saveHolding(capsule.id)} className="px-2 py-1 bg-purple-900/50 border border-purple-800 text-purple-300 text-[10px]">Add</button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                                <div className="flex justify-end gap-3 text-[10px]"><button onClick={() => openCapsuleForm(capsule)} className="text-slate-400 hover:text-white flex items-center gap-1"><Edit2 size={10} /> Edit</button><button onClick={() => openCapsuleDeleteModal(capsule)} className="text-slate-400 hover:text-rose-400 flex items-center gap-1"><Trash2 size={10} /> Delete</button></div>
                            </div>
                        );
                    })}
                </div>
                <div className="mt-6">
                    <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3">Auto Allocation Rules</h2>
                    <div className="space-y-2">
                        {capsuleRules.length === 0 ? <p className="text-xs text-slate-600">No auto allocation rules.</p> : capsuleRules.map((rule) => (
                            <div key={rule.id} className="bg-slate-800/30 border border-slate-700 p-2 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2 text-xs">
                                <div>
                                    <p className="text-slate-200">{rule.trigger_type} {rule.trigger_category ? `/ ${rule.trigger_category}` : ''} → {rule.capsule_name}</p>
                                    <p className="text-[10px] text-slate-500">
                                        {rule.amount_type === 'percentage' ? `${rule.amount_value}%` : formatCurrency(rule.amount_value)}
                                        {' from '}
                                        {rule.source_mode === 'fixed_account' ? rule.source_account_name || 'fixed account' : 'transaction account'}
                                        {rule.trigger_description ? ` / ${rule.trigger_description}` : ''}
                                    </p>
                                </div>
                                <button onClick={() => removeCapsuleRule(rule.id)} className="text-slate-500 hover:text-rose-400 justify-self-end"><Trash2 size={12} /></button>
                            </div>
                        ))}
                    </div>
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

            {capsuleDeleteModal && (
                <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
                    <div className="bg-slate-900 border border-rose-800/60 p-6 w-full max-w-md">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-sm font-medium text-rose-300 flex items-center gap-2">
                                <Trash2 size={14} /> Delete Capsule
                            </h2>
                            <button
                                onClick={() => setCapsuleDeleteModal(null)}
                                disabled={capsuleDeleteModal.confirming}
                                className="text-slate-400 hover:text-white disabled:opacity-40"
                            >
                                <X size={16} />
                            </button>
                        </div>

                        <p className="text-sm text-slate-300 mb-1">
                            Are you sure you want to delete <span className="text-white font-medium">"{capsuleDeleteModal.capsuleName}"</span>?
                        </p>
                        <p className="text-xs text-slate-500 mb-4">
                            All linked Auto Allocation Rules will also be permanently deleted.
                        </p>

                        <div className="flex justify-between items-center bg-slate-800/50 border border-slate-700 px-3 py-2 text-xs mb-4">
                            <span className="text-slate-400">Current balance</span>
                            <span className={`font-mono-nums ${capsuleDeleteModal.currentBalance > 0 ? 'text-amber-400' : 'text-slate-500'}`}>
                                {formatCurrency(capsuleDeleteModal.currentBalance)}
                            </span>
                        </div>

                        {capsuleDeleteModal.currentBalance > 0 && (
                            <div className="mb-5">
                                <p className="text-[10px] text-amber-400 uppercase tracking-wider mb-2">
                                    ⚠ Balance detected — select transfer destination
                                </p>
                                <p className="text-[10px] text-slate-500 mb-2">
                                    The accumulated balance will be transferred to the selected account before deletion.
                                </p>
                                <select
                                    value={capsuleDeleteModal.transferAccountId}
                                    onChange={(e) =>
                                        setCapsuleDeleteModal({ ...capsuleDeleteModal, transferAccountId: e.target.value })
                                    }
                                    className="w-full bg-slate-800 border border-slate-600 px-3 py-2 text-xs text-slate-200"
                                    disabled={capsuleDeleteModal.confirming}
                                >
                                    <option value="">Select account...</option>
                                    {accounts
                                        .filter((a) => a.account_type === 'asset' && a.role !== 'earmarked' && a.is_active)
                                        .map((a) => (
                                            <option key={a.id} value={a.id}>
                                                {a.name} ({formatCurrency(a.balance)})
                                            </option>
                                        ))}
                                </select>
                            </div>
                        )}

                        <div className="flex gap-2 justify-end">
                            <button
                                onClick={() => setCapsuleDeleteModal(null)}
                                disabled={capsuleDeleteModal.confirming}
                                className="px-4 py-2 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={confirmCapsuleDelete}
                                disabled={
                                    capsuleDeleteModal.confirming ||
                                    (capsuleDeleteModal.currentBalance > 0 && !capsuleDeleteModal.transferAccountId)
                                }
                                className="px-4 py-2 text-xs bg-rose-800 hover:bg-rose-700 text-rose-100 disabled:opacity-40 flex items-center gap-2"
                            >
                                <Trash2 size={12} />
                                {capsuleDeleteModal.confirming ? 'Deleting...' : 'Delete Capsule'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
