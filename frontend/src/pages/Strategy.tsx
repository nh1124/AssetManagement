import { useEffect, useState } from 'react';
import { AlertTriangle, Archive, ChevronLeft, ChevronRight, Copy, Edit2, Info, Plus, RefreshCw, Save, SlidersHorizontal, Sparkles, Trash2, Unlink, X } from 'lucide-react';
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
    deleteMonthlyPlanLine,
    getAccounts,
    getBudgetSummary,
    getCapsuleRules,
    getCapsules,
    getLifeEvents,
    getProducts,
    processCapsuleContributions,
    saveMonthlyPlanLines,
    suggestBudget,
    updateAccount,
    updateCapsule,
} from '../api';
import { formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import type {
    Account,
    Capsule,
    CapsuleRule,
    LifeEvent,
    MonthlyPlanLine,
    MonthlyPlanTargetType,
    MonthlyPlanLineType,
    Product,
    Transaction,
} from '../types';

interface BudgetAccount {
    id: number;
    account_id?: number | null;
    target_type?: MonthlyPlanTargetType | null;
    target_id?: number | null;
    source_account_id?: number | null;
    name: string;
    amount: number;
    balance: number;
    plan_line_id?: number | null;
    planned_date?: string | null;
    priority?: number;
    note?: string | null;
    recurring_amount?: number;
    recurring_transaction_id?: number | null;
    recurring_transaction_ids?: number[];
    recurring_items?: Array<{
        id: number;
        name: string;
        amount: number;
        original_amount: number;
        currency: string;
    }>;
    source?: string | null;
    sync_status?: 'synced' | 'missing' | 'diff' | null;
}

interface BudgetSummary {
    period: string;
    required_monthly_savings: number;
    monthly_fixed_costs: number;
    monthly_income: number;
    recurring_debt_payments?: number;
    recurring_allocations?: number;
    recurring_borrowing?: number;
    total_income_plan?: number;
    total_expected_inflow?: number;
    total_variable_budget: number;
    total_allocation_plan?: number;
    total_debt_plan?: number;
    total_capsule_plan: number;
    total_capsule_actual: number;
    remaining_balance: number;
    starting_cash?: number;
    ending_cash_after_plan?: number;
    feasibility_status?: 'ok' | 'warning' | 'shortfall';
    expense_accounts: BudgetAccount[];
    plan_lines?: MonthlyPlanLine[];
    cash_flow_projection?: Array<{
        period: string;
        inflow: number;
        expense: number;
        allocation: number;
        debt: number;
        net_cash: number;
        ending_cash: number;
        status: 'ok' | 'warning' | 'shortfall';
        setup_warnings?: Array<{
            type: 'missing_budget' | 'amount_diff';
            recurring_transaction_id: number;
            name: string;
            amount: number;
            budget_amount?: number;
        }>;
    }>;
    cash_flow_summary?: {
        runway_months: number;
        lowest_cash: number;
        required_buffer: number;
        shortfall_month?: string | null;
        horizon_months: number;
    };
    others_actual: number;
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
type EditablePlanLine = MonthlyPlanLine & { local_id: string };

const TABS = [
    { id: 'budgeting', label: 'Budgeting' },
    { id: 'capsules', label: 'Capsules' },
];

export default function Strategy() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [activeTab, setActiveTab] = useState('budgeting');
    const [currentPeriod, setCurrentPeriod] = useState(new Date().toISOString().slice(0, 7));
    const [cashFlowStartPeriod, setCashFlowStartPeriod] = useState(new Date().toISOString().slice(0, 7));
    const [cashFlowMonths, setCashFlowMonths] = useState(12);
    const [showCashFlowSettings, setShowCashFlowSettings] = useState(false);
    const [budgetSummary, setBudgetSummary] = useState<BudgetSummary | null>(null);
    const [budgetEdits, setBudgetEdits] = useState<Record<number, number>>({});
    const [showBudgetCategoryForm, setShowBudgetCategoryForm] = useState(false);
    const [expandedPlanForm, setExpandedPlanForm] = useState<MonthlyPlanLineType | null>(null);
    const [editingBudgetAccount, setEditingBudgetAccount] = useState<BudgetAccount | null>(null);
    const [budgetCategoryForm, setBudgetCategoryForm] = useState({ name: '', amount: '' });
    const [budgetThinking, setBudgetThinking] = useState(false);
    const [allExpenseAccounts, setAllExpenseAccounts] = useState<Account[]>([]);
    const [categorySearch, setCategorySearch] = useState('');
    const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
    const [showCategoryDropdown, setShowCategoryDropdown] = useState(false);
    const [planLineDrafts, setPlanLineDrafts] = useState<EditablePlanLine[]>([]);
    const [planLineForm, setPlanLineForm] = useState<{
        line_type: MonthlyPlanLineType;
        target_type: MonthlyPlanTargetType;
        target_id: string;
        account_id: string;
        name: string;
        amount: string;
        source: 'manual' | 'one_time';
        planned_date: string;
    }>({
        line_type: 'allocation',
        target_type: 'account',
        target_id: '',
        account_id: '',
        name: '',
        amount: '',
        source: 'manual',
        planned_date: `${currentPeriod}-01`,
    });
    const [products, setProducts] = useState<Product[]>([]);
    const [lifeEvents, setLifeEvents] = useState<LifeEvent[]>([]);

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
    const [capsuleForm, setCapsuleForm] = useState({ name: '', target_amount: '', current_balance: '0' });
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
    const calculatedRemaining = budgetSummary?.remaining_balance ?? 0;
    const formatCurrency = (value: number | undefined | null) =>
        formatCurrencyWithSetting(value, currentClient?.general_settings?.currency);

    const fetchBudgetSummary = async (period = currentPeriod) => {
        try {
            const summary = await getBudgetSummary(period, {
                cash_flow_start_period: cashFlowStartPeriod,
                cash_flow_months: cashFlowMonths,
            });
            const edits: Record<number, number> = {};
            summary.expense_accounts.forEach((account: BudgetAccount) => {
                edits[account.id] = account.amount;
            });
            setBudgetSummary(summary);
            setBudgetEdits(edits);
            setPlanLineDrafts((summary.plan_lines ?? [])
                .filter((line: MonthlyPlanLine) => line.line_type !== 'expense')
                .map((line: MonthlyPlanLine, index: number) => ({
                    ...line,
                    local_id: line.id ? `id-${line.id}` : `virtual-${line.line_type}-${line.target_type}-${line.target_id ?? line.name ?? index}`,
                })));
        } catch (error) {
            console.error('Failed to fetch budget summary:', error);
            showToast('Failed to load budget summary', 'error');
        }
    };

    const fetchBudgetReferences = async () => {
        try {
            const [accountData, capsuleData, productData, eventData] = await Promise.all([
                getAccounts(),
                getCapsules(),
                getProducts(),
                getLifeEvents(),
            ]);
            setAccounts(accountData);
            setCapsules(capsuleData);
            setProducts(productData);
            setLifeEvents(eventData);
        } catch (error) {
            console.error('Failed to fetch budget references:', error);
            showToast('Failed to load budget options', 'error');
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
        if (activeTab === 'budgeting') {
            fetchBudgetSummary();
            fetchBudgetReferences();
        }
        if (activeTab === 'capsules') fetchCapsules();
    }, [activeTab, currentPeriod, cashFlowStartPeriod, cashFlowMonths]);

    const changePeriod = (delta: number) => {
        const [year, month] = currentPeriod.split('-').map(Number);
        const date = new Date(year, month - 1 + delta, 1);
        setCurrentPeriod(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`);
    };

    const shiftPlannedDateToPeriod = (plannedDate: string | null | undefined, period: string) => {
        if (!plannedDate) return null;
        const day = plannedDate.slice(8, 10) || '01';
        return `${period}-${day}`;
    };

    const budgetAccountPlanPayload = (account: BudgetAccount, amount: number, period = currentPeriod) => ({
        id: account.plan_line_id ?? null,
        target_period: period,
        line_type: 'expense',
        target_type: account.target_type ?? 'account',
        target_id: account.target_id ?? null,
        account_id: account.account_id ?? (account.target_type === 'account' ? account.id : null),
        source_account_id: account.source_account_id ?? null,
        name: account.name ?? null,
        amount,
        planned_date: account.source === 'one_time' ? shiftPlannedDateToPeriod(account.planned_date, period) : null,
        priority: account.priority ?? 2,
        note: account.note ?? null,
        source: account.source === 'recurrence' ? 'recurrence' : account.source === 'one_time' ? 'one_time' : 'manual',
        recurring_transaction_id: account.source === 'recurrence' ? account.recurring_transaction_id ?? null : null,
        is_active: true,
    });

    const copyPreviousBudget = async () => {
        const [year, month] = currentPeriod.split('-').map(Number);
        const previousDate = new Date(year, month - 2, 1);
        const previousPeriod = `${previousDate.getFullYear()}-${String(previousDate.getMonth() + 1).padStart(2, '0')}`;
        try {
            const previousSummary = await getBudgetSummary(previousPeriod);
            if (previousSummary.expense_accounts.length === 0) {
                showToast('前月に予算設定がありません', 'info');
                return;
            }
            await saveMonthlyPlanLines(previousSummary.expense_accounts.map((account: BudgetAccount) => ({
                ...budgetAccountPlanPayload(account, account.amount, currentPeriod),
                id: null,
            })));
            showToast(`Copied from ${previousPeriod}`, 'info');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to copy previous budget', 'error');
        }
    };

    const saveBudget = async () => {
        try {
            const expenseLines = Object.entries(budgetEdits).flatMap(([accountId, amount]) => {
                const account = budgetSummary?.expense_accounts.find((item) => item.id === Number(accountId));
                if (account?.source === 'recurrence' && !account.plan_line_id) return [];
                if (!account) return [];
                return [budgetAccountPlanPayload(account, amount)];
            });
            const otherLines = planLineDrafts
                .filter((line) => !(line.source === 'recurrence' && !line.id))
                .map((line) => ({
                id: line.id ?? null,
                target_period: currentPeriod,
                line_type: line.line_type,
                target_type: line.target_type,
                target_id: line.target_id ?? null,
                account_id: line.account_id ?? null,
                source_account_id: line.source_account_id ?? null,
                name: line.name || line.target_name || null,
                amount: Number(line.amount || 0),
                planned_date: line.source === 'one_time' ? line.planned_date ?? `${currentPeriod}-01` : null,
                priority: line.priority ?? 2,
                note: line.note ?? null,
                source: line.source === 'recurrence' ? 'recurrence' : line.source === 'one_time' ? 'one_time' : 'manual',
                recurring_transaction_id: line.source === 'recurrence' ? line.recurring_transaction_id ?? null : null,
                is_active: true,
            }));
            await saveMonthlyPlanLines([...expenseLines, ...otherLines]);
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

    const openBudgetCategoryForm = async (account?: BudgetAccount) => {
        setEditingBudgetAccount(account ?? null);
        setBudgetCategoryForm(account
            ? { name: account.name, amount: String(budgetEdits[account.id] ?? account.amount ?? 0) }
            : { name: '', amount: '' });
        setCategorySearch('');
        setSelectedAccountId(null);
        setShowCategoryDropdown(false);
        if (!account) {
            const all = await getAccounts('expense');
            setAllExpenseAccounts(all);
        }
        setShowBudgetCategoryForm(true);
    };

    const saveBudgetCategory = async () => {
        const amount = Number(budgetCategoryForm.amount || '0') || 0;
        try {
            if (editingBudgetAccount) {
                const name = budgetCategoryForm.name.trim();
                if (!name) return;
                await updateAccount(editingBudgetAccount.id, { name });
                await saveMonthlyPlanLines([{
                    id: editingBudgetAccount.plan_line_id ?? null,
                    account_id: editingBudgetAccount.id,
                    target_period: currentPeriod,
                    line_type: 'expense',
                    target_type: 'account',
                    name,
                    amount,
                }]);
                showToast('Budget category updated', 'success');
            } else if (selectedAccountId !== null) {
                const account = allExpenseAccounts.find((item) => item.id === selectedAccountId);
                await saveMonthlyPlanLines([{
                    account_id: selectedAccountId,
                    target_period: currentPeriod,
                    line_type: 'expense',
                    target_type: 'account',
                    name: account?.name ?? null,
                    amount,
                }]);
                showToast('Budget category added', 'success');
            } else {
                const name = categorySearch.trim();
                if (!name) return;
                const created = await createAccount({ name, account_type: 'expense', balance: 0 });
                await saveMonthlyPlanLines([{
                    account_id: created.id,
                    target_period: currentPeriod,
                    line_type: 'expense',
                    target_type: 'account',
                    name: created.name,
                    amount,
                }]);
                showToast('Budget category added', 'success');
            }
            setShowBudgetCategoryForm(false);
            setEditingBudgetAccount(null);
            setBudgetCategoryForm({ name: '', amount: '' });
            setCategorySearch('');
            setSelectedAccountId(null);
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to save budget category', 'error');
        }
    };

    const removeBudgetCategory = async (accountId: number, planLineId?: number | null) => {
        try {
            if (!planLineId) {
                throw new Error('No plan line id');
            }
            await deleteMonthlyPlanLine(planLineId);
            setBudgetEdits(prev => {
                const { [accountId]: _, ...rest } = prev;
                return rest;
            });
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to remove budget category', 'error');
        }
    };

    const openPlanLineForm = (lineType: MonthlyPlanLineType) => {
        setExpandedPlanForm(expandedPlanForm === lineType ? null : lineType);
        setPlanLineForm({
            line_type: lineType,
            target_type: lineType === 'allocation' || lineType === 'debt_payment' ? 'account' : 'manual',
            target_id: '',
            account_id: '',
            name: '',
            amount: '',
            source: 'manual',
            planned_date: `${currentPeriod}-01`,
        });
    };

    const openOneTimePlanForm = (lineType: MonthlyPlanLineType) => {
        setExpandedPlanForm(lineType);
        setPlanLineForm({
            line_type: lineType,
            target_type: 'manual',
            target_id: '',
            account_id: '',
            name: '',
            amount: '',
            source: 'one_time',
            planned_date: `${currentPeriod}-01`,
        });
    };

    const planTargetLabel = (line: MonthlyPlanLine) => line.target_name || line.name || line.account_name || 'Manual line';

    const planLineKey = (line: Partial<MonthlyPlanLine> & { name?: string | null }) => {
        const accountId = line.account_id ?? 0;
        const targetId = line.target_id ?? 0;
        const name = accountId || targetId ? '' : (line.name || line.target_name || '').trim().toLowerCase();
        return `${line.line_type || ''}|${line.target_type || 'manual'}|${accountId}|${targetId}|${name}`;
    };

    const recurringContextFor = (line: Partial<MonthlyPlanLine>) => {
        const key = planLineKey(line);
        return [...planLineDrafts, ...(budgetSummary?.plan_lines ?? [])].find((candidate) => (
            candidate.recurring_transaction_id && planLineKey(candidate) === key
        ));
    };

    const updatePlanLineAmount = (localId: string, amount: number) => {
        setPlanLineDrafts((prev) => prev.map((line) => (
            line.local_id === localId ? { ...line, amount } : line
        )));
    };

    const syncRecurringBudgetAccount = async (account: BudgetAccount) => {
        if (!account.recurring_transaction_id) return;
        try {
            await saveMonthlyPlanLines([{
                id: account.plan_line_id ?? null,
                target_period: currentPeriod,
                line_type: 'expense',
                target_type: account.target_type ?? (account.account_id ? 'account' : 'manual'),
                target_id: account.target_id ?? null,
                account_id: account.account_id ?? null,
                source_account_id: account.source_account_id ?? null,
                name: account.name,
                amount: Number(account.recurring_amount || 0),
                planned_date: null,
                priority: 2,
                note: null,
                source: 'recurrence',
                recurring_transaction_id: account.recurring_transaction_id,
                is_active: true,
            }]);
            showToast('Synced with recurrence', 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to sync recurrence', 'error');
        }
    };

    const syncRecurringBudgetAccounts = async (accountsToSync: BudgetAccount[]) => {
        const payload = accountsToSync
            .filter((account) => account.recurring_transaction_id && account.sync_status !== 'synced')
            .map((account) => ({
                id: account.plan_line_id ?? null,
                target_period: currentPeriod,
                line_type: 'expense',
                target_type: account.target_type ?? (account.account_id ? 'account' : 'manual'),
                target_id: account.target_id ?? null,
                account_id: account.account_id ?? null,
                source_account_id: account.source_account_id ?? null,
                name: account.name,
                amount: Number(account.recurring_amount || 0),
                planned_date: null,
                priority: 2,
                note: null,
                source: 'recurrence',
                recurring_transaction_id: account.recurring_transaction_id ?? null,
                is_active: true,
            }));
        if (payload.length === 0) {
            showToast('No recurrence differences to sync', 'info');
            return;
        }
        try {
            await saveMonthlyPlanLines(payload);
            showToast(`Synced ${payload.length} recurrence item${payload.length === 1 ? '' : 's'}`, 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to sync recurrences', 'error');
        }
    };

    const syncRecurringPlanLine = async (line: EditablePlanLine) => {
        if (!line.recurring_transaction_id) return;
        try {
            await saveMonthlyPlanLines([{
                id: line.id ?? null,
                target_period: currentPeriod,
                line_type: line.line_type,
                target_type: line.target_type,
                target_id: line.target_id ?? null,
                account_id: line.account_id ?? null,
                source_account_id: line.source_account_id ?? null,
                name: line.name || line.target_name || null,
                amount: Number(line.recurring_amount || 0),
                planned_date: null,
                priority: line.priority ?? 2,
                note: line.note ?? null,
                source: 'recurrence',
                recurring_transaction_id: line.recurring_transaction_id,
                is_active: true,
            }]);
            showToast('Synced with recurrence', 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to sync recurrence', 'error');
        }
    };

    const syncRecurringPlanLines = async (lines: EditablePlanLine[]) => {
        const payload = lines
            .filter((line) => line.recurring_transaction_id && line.sync_status !== 'synced')
            .map((line) => ({
                id: line.id ?? null,
                target_period: currentPeriod,
                line_type: line.line_type,
                target_type: line.target_type,
                target_id: line.target_id ?? null,
                account_id: line.account_id ?? null,
                source_account_id: line.source_account_id ?? null,
                name: line.name || line.target_name || null,
                amount: Number(line.recurring_amount || 0),
                planned_date: null,
                priority: line.priority ?? 2,
                note: line.note ?? null,
                source: 'recurrence',
                recurring_transaction_id: line.recurring_transaction_id ?? null,
                is_active: true,
            }));
        if (payload.length === 0) {
            showToast('No recurrence differences to sync', 'info');
            return;
        }
        try {
            await saveMonthlyPlanLines(payload);
            showToast(`Synced ${payload.length} recurrence item${payload.length === 1 ? '' : 's'}`, 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to sync recurrences', 'error');
        }
    };

    const syncAllRecurrencesForPeriod = async (period: string) => {
        try {
            const summary = period === currentPeriod
                ? budgetSummary
                : await getBudgetSummary(period, { cash_flow_start_period: period, cash_flow_months: 1 });
            if (!summary) return;
            const expensePayload = (summary.expense_accounts ?? [])
                .filter((account: BudgetAccount) => account.recurring_transaction_id && account.sync_status !== 'synced')
                .map((account: BudgetAccount) => ({
                    id: account.plan_line_id ?? null,
                    target_period: period,
                    line_type: 'expense',
                    target_type: account.target_type ?? (account.account_id ? 'account' : 'manual'),
                    target_id: account.target_id ?? null,
                    account_id: account.account_id ?? null,
                    source_account_id: account.source_account_id ?? null,
                    name: account.name,
                    amount: Number(account.recurring_amount || 0),
                    planned_date: null,
                    priority: 2,
                    note: null,
                    source: 'recurrence',
                    recurring_transaction_id: account.recurring_transaction_id ?? null,
                    is_active: true,
                }));
            const planPayload = (summary.plan_lines ?? [])
                .filter((line: MonthlyPlanLine) => line.line_type !== 'expense' && line.recurring_transaction_id && line.sync_status !== 'synced')
                .map((line: MonthlyPlanLine) => ({
                    id: line.id ?? null,
                    target_period: period,
                    line_type: line.line_type,
                    target_type: line.target_type,
                    target_id: line.target_id ?? null,
                    account_id: line.account_id ?? null,
                    source_account_id: line.source_account_id ?? null,
                    name: line.name || line.target_name || null,
                    amount: Number(line.recurring_amount || 0),
                    planned_date: null,
                    priority: line.priority ?? 2,
                    note: line.note ?? null,
                    source: 'recurrence',
                    recurring_transaction_id: line.recurring_transaction_id ?? null,
                    is_active: true,
                }));
            const payload = [...expensePayload, ...planPayload];
            if (payload.length === 0) {
                showToast('No recurrence differences to sync', 'info');
                return;
            }
            await saveMonthlyPlanLines(payload);
            showToast(`Synced ${payload.length} recurrence item${payload.length === 1 ? '' : 's'} for ${period}`, 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to sync recurrences', 'error');
        }
    };

    const unlinkRecurringBudgetAccount = async (account: BudgetAccount) => {
        if (!account.plan_line_id) return;
        try {
            await saveMonthlyPlanLines([{
                id: account.plan_line_id,
                target_period: currentPeriod,
                line_type: 'expense',
                target_type: account.target_type ?? (account.account_id ? 'account' : 'manual'),
                target_id: account.target_id ?? null,
                account_id: account.account_id ?? null,
                source_account_id: account.source_account_id ?? null,
                name: account.name,
                amount: Number(budgetEdits[account.id] ?? account.amount ?? 0),
                planned_date: null,
                priority: 2,
                note: null,
                source: 'manual',
                recurring_transaction_id: null,
                is_active: true,
            }]);
            showToast('Recurrence sync removed', 'info');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to remove recurrence sync', 'error');
        }
    };

    const unlinkRecurringPlanLine = async (line: EditablePlanLine) => {
        if (!line.id) return;
        try {
            await saveMonthlyPlanLines([{
                id: line.id,
                target_period: currentPeriod,
                line_type: line.line_type,
                target_type: line.target_type,
                target_id: line.target_id ?? null,
                account_id: line.account_id ?? null,
                source_account_id: line.source_account_id ?? null,
                name: line.name || line.target_name || null,
                amount: Number(line.amount || 0),
                planned_date: null,
                priority: line.priority ?? 2,
                note: line.note ?? null,
                source: 'manual',
                recurring_transaction_id: null,
                is_active: true,
            }]);
            showToast('Recurrence sync removed', 'info');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to remove recurrence sync', 'error');
        }
    };

    const jumpToCashFlowPeriod = (period: string) => {
        setCurrentPeriod(period);
        setCashFlowStartPeriod(period);
    };

    const copyCurrentBudgetToPeriod = async (targetPeriod: string) => {
        if (targetPeriod === currentPeriod) {
            showToast('Already on this month', 'info');
            return;
        }
        try {
            const targetSummary = await getBudgetSummary(targetPeriod, { cash_flow_start_period: targetPeriod, cash_flow_months: 1 });
            const targetByKey = new Map<string, MonthlyPlanLine>();
            (targetSummary.plan_lines ?? []).forEach((line: MonthlyPlanLine) => {
                if (line.id) targetByKey.set(planLineKey(line), line);
            });

            const expensePayload = (budgetSummary?.expense_accounts ?? [])
                .filter((account) => account.plan_line_id)
                .map((account) => {
                    const sourceLine = {
                        line_type: 'expense' as MonthlyPlanLineType,
                        target_type: account.target_type ?? 'account',
                        account_id: account.account_id ?? (account.target_type === 'account' ? account.id : null),
                        target_id: account.target_id ?? null,
                        name: account.name,
                    };
                    const targetLine = targetByKey.get(planLineKey(sourceLine));
                    return {
                        ...budgetAccountPlanPayload(account, Number(budgetEdits[account.id] ?? account.amount ?? 0), targetPeriod),
                        id: targetLine?.id ?? null,
                    };
                });
            const planPayload = planLineDrafts
                .filter((line) => line.id && line.line_type !== 'expense')
                .map((line) => {
                    const targetLine = targetByKey.get(planLineKey(line));
                    return {
                        id: targetLine?.id ?? null,
                        target_period: targetPeriod,
                        line_type: line.line_type,
                        target_type: line.target_type,
                        target_id: line.target_id ?? null,
                        account_id: line.account_id ?? null,
                        source_account_id: line.source_account_id ?? null,
                        name: line.name || line.target_name || null,
                        amount: Number(line.amount || 0),
                        planned_date: line.source === 'one_time' ? shiftPlannedDateToPeriod(line.planned_date, targetPeriod) : null,
                        priority: line.priority ?? 2,
                        note: line.note ?? null,
                        source: line.source === 'recurrence' ? 'recurrence' : line.source === 'one_time' ? 'one_time' : 'manual',
                        recurring_transaction_id: line.source === 'recurrence' ? line.recurring_transaction_id ?? null : null,
                        is_active: true,
                    };
                });
            const payload = [...expensePayload, ...planPayload];
            if (payload.length === 0) {
                showToast('Save this month before copying', 'info');
                return;
            }
            await saveMonthlyPlanLines(payload);
            showToast(`Copied current budget to ${targetPeriod}`, 'success');
            await fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to copy budget to month', 'error');
        }
    };

    const addPlanLine = async () => {
        const amount = Number(planLineForm.amount || '0') || 0;
        let targetType = planLineForm.target_type;
        let targetId: number | null = planLineForm.target_id ? Number(planLineForm.target_id) : null;
        let accountId: number | null = planLineForm.account_id ? Number(planLineForm.account_id) : null;
        let name = planLineForm.name.trim();

        if (targetType === 'account' && accountId) {
            name = accounts.find((account) => account.id === accountId)?.name ?? name;
            targetId = null;
        } else if (targetType === 'capsule' && targetId) {
            const capsule = capsules.find((item) => item.id === targetId);
            name = capsule?.name ?? name;
            accountId = capsule?.account_id ?? null;
        } else if (targetType === 'life_event' && targetId) {
            name = lifeEvents.find((event) => event.id === targetId)?.name ?? name;
            accountId = null;
        } else if (targetType === 'product' && targetId) {
            name = products.find((product) => product.id === targetId)?.name ?? name;
            accountId = null;
        } else {
            targetType = 'manual';
            targetId = null;
            accountId = null;
        }

        if (!name && targetType === 'manual') return;
        if (planLineForm.line_type === 'expense') {
            try {
                await saveMonthlyPlanLines([{
                    id: null,
                    target_period: currentPeriod,
                    line_type: 'expense',
                    target_type: targetType,
                    target_id: targetId,
                    account_id: accountId,
                    source_account_id: null,
                    name,
                    amount,
                    planned_date: planLineForm.source === 'one_time' ? planLineForm.planned_date || `${currentPeriod}-01` : null,
                    priority: 2,
                    note: null,
                    source: planLineForm.source,
                    recurring_transaction_id: null,
                    is_active: true,
                }]);
                setPlanLineForm({
                    line_type: planLineForm.line_type,
                    target_type: 'manual',
                    target_id: '',
                    account_id: '',
                    name: '',
                    amount: '',
                    source: 'manual',
                    planned_date: `${currentPeriod}-01`,
                });
                setExpandedPlanForm(null);
                await fetchBudgetSummary();
            } catch (error) {
                showToast('Failed to add plan line', 'error');
            }
            return;
        }

        const localId = `new-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const recurringContext = recurringContextFor({
            target_period: currentPeriod,
            line_type: planLineForm.line_type,
            target_type: targetType,
            target_id: targetId,
            account_id: accountId,
            name,
        });
        setPlanLineDrafts((prev) => ([
            ...prev,
            {
                local_id: localId,
                target_period: currentPeriod,
                line_type: planLineForm.line_type,
                target_type: targetType,
                target_id: targetId,
                account_id: accountId,
                name,
                target_name: name,
                amount,
                planned_date: planLineForm.source === 'one_time' ? planLineForm.planned_date || `${currentPeriod}-01` : null,
                actual: 0,
                variance: amount,
                priority: 2,
                source: planLineForm.source,
                recurring_transaction_id: recurringContext?.recurring_transaction_id ?? null,
                recurring_transaction_ids: recurringContext?.recurring_transaction_ids ?? [],
                recurring_items: recurringContext?.recurring_items ?? [],
                recurring_amount: recurringContext?.recurring_amount ?? 0,
                sync_status: recurringContext ? 'diff' : null,
                is_active: true,
            },
        ]));
        setPlanLineForm({
            line_type: planLineForm.line_type,
            target_type: 'account',
            target_id: '',
            account_id: '',
            name: '',
            amount: '',
            source: 'manual',
            planned_date: `${currentPeriod}-01`,
        });
        setExpandedPlanForm(null);
    };

    const removePlanLine = async (line: EditablePlanLine) => {
        try {
            if (line.id) {
                await deleteMonthlyPlanLine(line.id);
                await fetchBudgetSummary();
                return;
            }
            if (line.source === 'capsule' && line.target_type === 'capsule' && line.target_id) {
                await saveMonthlyPlanLines([{
                    target_period: currentPeriod,
                    line_type: 'allocation',
                    target_type: 'capsule',
                    target_id: line.target_id,
                    account_id: line.account_id ?? null,
                    name: line.name || line.target_name || null,
                    amount: 0,
                    priority: line.priority ?? 2,
                    is_active: true,
                }]);
                await fetchBudgetSummary();
                return;
            }
            setPlanLineDrafts((prev) => prev.filter((item) => item.local_id !== line.local_id));
        } catch (error) {
            showToast('Failed to remove plan line', 'error');
        }
    };

    const openCapsuleForm = (capsule?: Capsule) => {
        setEditingCapsuleId(capsule?.id ?? null);
        setCapsuleForm(capsule
            ? {
                name: capsule.name,
                target_amount: String(capsule.target_amount),
                current_balance: '0',
            }
            : { name: '', target_amount: '', current_balance: '0' });
        setShowCapsuleForm(true);
    };

    const saveCapsule = async () => {
        if (!capsuleForm.name || !capsuleForm.target_amount) return;
        const payload = {
            name: capsuleForm.name,
            target_amount: Number(capsuleForm.target_amount),
            monthly_contribution: editingCapsuleId
                ? capsules.find((capsule) => capsule.id === editingCapsuleId)?.monthly_contribution ?? 0
                : 0,
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
        const variableRecurringTotal = (budgetSummary?.expense_accounts ?? []).reduce((sum, account) => sum + Number(account.recurring_amount || 0), 0);
        const variableSyncableAccounts = (budgetSummary?.expense_accounts ?? []).filter((account) => account.recurring_transaction_id && account.sync_status !== 'synced');
        const cashFlowSummary = budgetSummary?.cash_flow_summary;
        const cashFlowHorizon = cashFlowSummary?.horizon_months ?? budgetSummary?.cash_flow_projection?.length ?? 12;
        const runwayLabel = cashFlowSummary
            ? cashFlowSummary.shortfall_month
                ? `${cashFlowSummary.runway_months} mo`
                : `${cashFlowHorizon}+ mo`
            : '-';
        const language = String(currentClient?.general_settings?.language || 'ja').toLowerCase();
        const isJapanese = language.startsWith('ja');
        const tableHelp = {
            income: {
                en: 'Planned cash inflows for this month, including income, borrowing, and asset drawdowns.',
                ja: '今月の資金流入計画です。収入、借入、資産取り崩しを含みます。',
            },
            variable: {
                en: 'Flexible spending limits for expense categories. These reduce available monthly cash.',
                ja: '費用カテゴリごとの変動支出予算です。今月使える現金を減らします。',
            },
            allocation: {
                en: 'Planned transfers into assets, capsules, reserves, or registry items.',
                ja: '資産、Capsule、予備費、Registry項目への配分計画です。',
            },
            debt: {
                en: 'Planned cash outflows for loan, credit, or other liability repayments.',
                ja: 'ローン、クレジット、その他負債の返済による資金流出計画です。',
            },
            projection: {
                en: 'A twelve-month cash forecast based on recurring transactions and monthly plan lines.',
                ja: '定期取引と月次計画行にもとづく12か月のキャッシュ予測です。',
            },
        };
        const helpText = (key: keyof typeof tableHelp) => tableHelp[key][isJapanese ? 'ja' : 'en'];
        const renderTitleWithInfo = (title: string, helpKey: keyof typeof tableHelp) => (
            <div className="flex items-center gap-1.5">
                <h2 className="text-xs text-slate-400 uppercase tracking-wider">{title}</h2>
                <span className="relative inline-flex group">
                    <Info size={12} className="text-slate-500 group-hover:text-cyan-400" />
                    <span className="pointer-events-none absolute left-1/2 top-5 z-20 hidden w-64 -translate-x-1/2 border border-slate-700 bg-slate-950 px-3 py-2 text-[10px] leading-relaxed text-slate-300 shadow-xl group-hover:block">
                        {helpText(helpKey)}
                    </span>
                </span>
            </div>
        );
        const targetOptions = (() => {
            if (planLineForm.target_type === 'account') {
                const allowedTypes =
                    planLineForm.line_type === 'income' ? ['income'] :
                    planLineForm.line_type === 'borrowing' || planLineForm.line_type === 'debt_payment' ? ['liability'] :
                    planLineForm.line_type === 'expense' ? ['expense'] :
                    ['asset'];
                return accounts
                    .filter((account) => allowedTypes.includes(account.account_type))
                    .map((account) => ({ id: account.id, label: `${account.name} / ${account.account_type}` }));
            }
            if (planLineForm.target_type === 'capsule') {
                return capsules.map((capsule) => ({ id: capsule.id, label: capsule.name }));
            }
            if (planLineForm.target_type === 'life_event') {
                return lifeEvents.map((event) => ({ id: event.id, label: event.name }));
            }
            if (planLineForm.target_type === 'product') {
                return products.map((product) => ({ id: product.id, label: `${product.name} / ${product.is_asset ? 'asset' : 'item'}` }));
            }
            return [];
        })();
        const planLinesFor = (types: MonthlyPlanLineType[]) =>
            planLineDrafts.filter((line) => types.includes(line.line_type));
        const planGroupTotal = (types: MonthlyPlanLineType[]) =>
            planLinesFor(types).reduce((sum, line) => sum + Number(line.amount || 0), 0);
        const planGroupActual = (types: MonthlyPlanLineType[]) =>
            planLinesFor(types).reduce((sum, line) => sum + Number(line.actual || 0), 0);
        const renderPlanLineForm = (lineType: MonthlyPlanLineType) => (
            expandedPlanForm === lineType && (
                <div className="mb-3 border border-cyan-800/40 bg-cyan-900/10 p-3">
                    <div className="grid grid-cols-12 gap-2">
                        <select
                            value={planLineForm.line_type}
                            onChange={(event) => setPlanLineForm({ ...planLineForm, line_type: event.target.value as MonthlyPlanLineType, target_id: '', account_id: '' })}
                            className="col-span-2 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                        >
                            {(lineType === 'income'
                                ? ['income', 'borrowing', 'drawdown']
                                : [lineType]
                            ).map((type) => <option key={type} value={type}>{type.replace('_', ' ')}</option>)}
                        </select>
                        <select
                            value={planLineForm.target_type}
                            onChange={(event) => setPlanLineForm({ ...planLineForm, target_type: event.target.value as MonthlyPlanTargetType, target_id: '', account_id: '' })}
                            className="col-span-2 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                        >
                            <option value="account">Account</option>
                            <option value="capsule">Capsule</option>
                            {lineType !== 'allocation' && <option value="life_event">LifeEvent</option>}
                            <option value="product">Asset/Item</option>
                            <option value="manual">Manual</option>
                        </select>
                        {planLineForm.target_type === 'manual' ? (
                            <input
                                value={planLineForm.name}
                                onChange={(event) => setPlanLineForm({ ...planLineForm, name: event.target.value })}
                                placeholder="Name"
                                className={`${planLineForm.source === 'one_time' ? 'col-span-2' : 'col-span-4'} bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs`}
                            />
                        ) : (
                            <select
                                value={planLineForm.target_type === 'account' ? planLineForm.account_id : planLineForm.target_id}
                                onChange={(event) => {
                                    const value = event.target.value;
                                    setPlanLineForm({
                                        ...planLineForm,
                                        account_id: planLineForm.target_type === 'account' ? value : '',
                                        target_id: planLineForm.target_type === 'account' ? '' : value,
                                    });
                                }}
                                className={`${planLineForm.source === 'one_time' ? 'col-span-2' : 'col-span-4'} bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs`}
                            >
                                <option value="">Target...</option>
                                {targetOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                            </select>
                        )}
                        {planLineForm.source === 'one_time' && (
                            <input
                                type="date"
                                value={planLineForm.planned_date}
                                onChange={(event) => setPlanLineForm({ ...planLineForm, planned_date: event.target.value })}
                                className="col-span-2 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                            />
                        )}
                        <input
                            type="number"
                            value={planLineForm.amount}
                            onChange={(event) => setPlanLineForm({ ...planLineForm, amount: event.target.value })}
                            placeholder="Amount"
                            className={`${planLineForm.source === 'one_time' ? 'col-span-2' : 'col-span-2'} bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums`}
                        />
                        <button type="button" onClick={addPlanLine} className="col-span-2 bg-cyan-700 hover:bg-cyan-600 text-white py-1.5 text-xs">
                            Add
                        </button>
                    </div>
                </div>
            )
        );
        const renderPlanSection = (
            title: string,
            types: MonthlyPlanLineType[],
            addType: MonthlyPlanLineType,
            emptyText: string,
            actualLabel = 'Actual',
        ) => {
            const rows = planLinesFor(types);
            const totalActual = planGroupActual(types);
            const totalPlan = planGroupTotal(types);
            const totalRecurring = rows.reduce((sum, line) => sum + Number(line.recurring_amount || 0), 0);
            const syncableRows = rows.filter((line) => line.recurring_transaction_id && line.sync_status !== 'synced');
            return (
                <div className="mt-6">
                    <div className="flex items-center justify-between mb-3">
                        {renderTitleWithInfo(
                            title,
                            addType === 'income' ? 'income' : addType === 'allocation' ? 'allocation' : 'debt',
                        )}
                        <div className="flex items-center gap-3">
                            <span className="text-xs text-slate-500 font-mono-nums">Total {formatCurrency(totalPlan)}</span>
                            <button
                                type="button"
                                title="Sync all recurrence differences"
                                disabled={syncableRows.length === 0}
                                onClick={() => syncRecurringPlanLines(syncableRows)}
                                className={`text-slate-500 ${syncableRows.length > 0 ? 'hover:text-amber-300' : 'opacity-30 cursor-not-allowed'}`}
                            >
                                <RefreshCw size={14} />
                            </button>
                            <button type="button" title={`Add ${title}`} onClick={() => openPlanLineForm(addType)} className="text-slate-500 hover:text-cyan-400">
                                <Plus size={14} />
                            </button>
                            <button type="button" title={`Add one-time ${title}`} onClick={() => openOneTimePlanForm(addType)} className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-cyan-300">
                                <Plus size={12} /> One-time
                            </button>
                        </div>
                    </div>
                    {renderPlanLineForm(addType)}
                    <div className="overflow-x-auto border border-slate-800">
                        <table className="w-full text-[10px]">
                            <thead className="text-slate-500 uppercase border-b border-slate-700 bg-slate-800/50">
                                <tr>
                                    <th className="px-2 py-2 text-left font-normal">Type</th>
                                    <th className="px-2 py-2 text-left font-normal">Target</th>
                                    <th className="px-2 py-2 text-right font-normal">{actualLabel}</th>
                                    <th className="px-2 py-2 text-right font-normal">Plan</th>
                                    <th className="px-2 py-2 text-right font-normal">Recurrence</th>
                                    <th className="px-2 py-2 text-right font-normal">Variance</th>
                                    <th className="px-2 py-2 text-right font-normal">Edit</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/70">
                                {rows.length === 0 ? (
                                    <tr><td colSpan={7} className="px-2 py-4 text-slate-600">{emptyText}</td></tr>
                                ) : rows.map((line) => {
                                    const variance = Number(line.amount || 0) - Number(line.actual || 0);
                                    const isRecurringControlled = line.source === 'recurrence';
                                    return (
                                        <tr key={line.local_id} className="hover:bg-slate-800/30 group">
                                            <td className="px-2 py-2 text-slate-400">{line.line_type.replace('_', ' ')}</td>
                                            <td className="px-2 py-2 text-slate-300">
                                                {planTargetLabel(line)}
                                                {line.source === 'one_time' && line.planned_date && (
                                                    <span className="ml-2 text-[9px] text-cyan-500 font-mono-nums">{line.planned_date}</span>
                                                )}
                                            </td>
                                            <td className="px-2 py-2 text-right font-mono-nums text-slate-500">{formatCurrency(line.actual)}</td>
                                            <td className="px-2 py-2 text-right">
                                                <input
                                                    type="number"
                                                    step="1000"
                                                    value={line.amount}
                                                    disabled={isRecurringControlled}
                                                    onChange={(event) => updatePlanLineAmount(line.local_id, Number(event.target.value) || 0)}
                                                    className={`w-24 bg-transparent border-b text-right font-mono-nums outline-none ${isRecurringControlled ? 'border-transparent text-slate-500' : 'border-slate-700 focus:border-cyan-500'}`}
                                                />
                                            </td>
                                            <td className={`px-2 py-2 text-right font-mono-nums ${(line.recurring_amount || 0) > 0 ? 'text-cyan-300' : 'text-slate-600'}`}>
                                                {(line.recurring_amount || 0) > 0 ? formatCurrency(line.recurring_amount) : '-'}
                                            </td>
                                            <td className={`px-2 py-2 text-right font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(variance)}</td>
                                            <td className="px-2 py-2 text-right">
                                                <div className="flex items-center justify-end gap-2">
                                                    {line.recurring_transaction_id && (
                                                        <button type="button" title={line.sync_status === 'synced' ? 'Synced with recurrence' : 'Sync with recurrence'} onClick={() => syncRecurringPlanLine(line)} className={line.sync_status === 'synced' ? 'text-cyan-400 hover:text-cyan-200' : 'text-amber-400 hover:text-amber-200'}>
                                                            <RefreshCw size={12} />
                                                        </button>
                                                    )}
                                                    {line.source === 'recurrence' && line.id && (
                                                        <button type="button" title="Remove recurrence sync" onClick={() => unlinkRecurringPlanLine(line)} className="text-slate-500 hover:text-amber-300">
                                                            <Unlink size={12} />
                                                        </button>
                                                    )}
                                                    {!isRecurringControlled && (
                                                        <button type="button" title="Remove line" onClick={() => removePlanLine(line)} className="text-slate-500 hover:text-rose-400"><Trash2 size={12} /></button>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                                <tr className="border-t border-slate-700 bg-slate-800/40">
                                    <td className="px-2 py-2 text-slate-100 font-medium">Total</td>
                                    <td className="px-2 py-2 text-slate-500">{title}</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-slate-300">{formatCurrency(totalActual)}</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-slate-200">{formatCurrency(totalPlan)}</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-cyan-300">{formatCurrency(totalRecurring)}</td>
                                    <td colSpan={2} />
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            );
        };

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
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Expected Inflow</p><p className="font-mono-nums text-emerald-300">{formatCurrency(budgetSummary?.total_expected_inflow)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Goal Savings</p><p className="font-mono-nums text-cyan-400">{formatCurrency(budgetSummary?.required_monthly_savings)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Fixed Costs</p><p className="font-mono-nums text-amber-400">{formatCurrency(budgetSummary?.monthly_fixed_costs)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Debt Pay</p><p className="font-mono-nums text-rose-300">{formatCurrency(budgetSummary?.total_debt_plan)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Allocations</p><p className="font-mono-nums text-cyan-300">{formatCurrency(budgetSummary?.total_allocation_plan)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Remaining</p><p className={`font-mono-nums ${calculatedRemaining >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(calculatedRemaining)}</p></div>
                        <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Ending Cash</p><p className={`font-mono-nums ${(budgetSummary?.ending_cash_after_plan ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(budgetSummary?.ending_cash_after_plan)}</p></div>
                    </div>
                </div>

                <div className="bg-slate-900/60 border border-slate-800 p-4 space-y-2">
                    <h2 className="text-xs text-slate-400 uppercase tracking-wider">Actions</h2>
                    <button onClick={copyPreviousBudget} className="w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 py-2 text-xs text-slate-300 flex items-center justify-center gap-2"><Copy size={14} /> Copy Previous Month</button>
                    <button onClick={applyBudgetSuggestions} disabled={budgetThinking} className="w-full bg-purple-900/40 hover:bg-purple-900/60 border border-purple-800 py-2 text-xs text-purple-200 flex items-center justify-center gap-2 disabled:opacity-50"><Sparkles size={14} /> {budgetThinking ? 'Thinking...' : 'AI Suggest Budget'}</button>
                    <button onClick={saveBudget} className="w-full bg-cyan-600 hover:bg-cyan-500 py-2 text-xs text-white flex items-center justify-center gap-2"><Save size={14} /> Save {currentPeriod}</button>
                </div>
            </section>

            <section className="bg-slate-900/60 border border-slate-800 p-4 overflow-auto">
                <div className="mb-8">
                    {renderPlanSection('Income Plan', ['income', 'borrowing', 'drawdown'], 'income', 'No expected inflows yet.')}
                </div>

                <div className="flex items-center justify-between mb-3">
                    {renderTitleWithInfo('Variable Budget', 'variable')}
                    <div className="flex items-center gap-3">
                        <span className="text-xs text-slate-500 font-mono-nums">Total {formatCurrency(variableBudgetTotal)}</span>
                        <button
                            type="button"
                            title="Sync all recurrence differences"
                            disabled={variableSyncableAccounts.length === 0}
                            onClick={() => syncRecurringBudgetAccounts(variableSyncableAccounts)}
                            className={`text-slate-500 ${variableSyncableAccounts.length > 0 ? 'hover:text-amber-300' : 'opacity-30 cursor-not-allowed'}`}
                        >
                            <RefreshCw size={14} />
                        </button>
                        <button type="button" title="Add category" onClick={() => openBudgetCategoryForm()} className="text-slate-500 hover:text-emerald-400">
                            <Plus size={14} />
                        </button>
                        <button type="button" title="Add one-time expense" onClick={() => openOneTimePlanForm('expense')} className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-cyan-300">
                            <Plus size={12} /> One-time
                        </button>
                    </div>
                </div>

                {renderPlanLineForm('expense')}

                {showBudgetCategoryForm && (() => {
                    const currentBudgetIds = new Set((budgetSummary?.expense_accounts ?? []).map(a => a.id));
                    const filtered = allExpenseAccounts.filter(a =>
                        !currentBudgetIds.has(a.id) &&
                        a.name.toLowerCase().includes(categorySearch.toLowerCase())
                    );
                    const showCreateNew = categorySearch.trim() !== '' &&
                        !filtered.some(a => a.name.toLowerCase() === categorySearch.trim().toLowerCase());
                    return (
                        <div className="mb-3 border border-emerald-800/40 bg-emerald-900/10 p-3 space-y-2">
                            <div className="grid grid-cols-12 gap-2 items-start">
                                {editingBudgetAccount ? (
                                    <input
                                        value={budgetCategoryForm.name}
                                        onChange={e => setBudgetCategoryForm({ ...budgetCategoryForm, name: e.target.value })}
                                        placeholder="Category name"
                                        className="col-span-5 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                    />
                                ) : (
                                    <div className="col-span-5 relative">
                                        <input
                                            value={categorySearch}
                                            onChange={e => {
                                                setCategorySearch(e.target.value);
                                                setSelectedAccountId(null);
                                                setShowCategoryDropdown(true);
                                            }}
                                            onFocus={() => setShowCategoryDropdown(true)}
                                            onBlur={() => setTimeout(() => setShowCategoryDropdown(false), 150)}
                                            placeholder="Search or type new..."
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                        />
                                        {showCategoryDropdown && (filtered.length > 0 || showCreateNew) && (
                                            <div className="absolute z-10 top-full left-0 right-0 bg-slate-900 border border-slate-700 max-h-40 overflow-y-auto">
                                                {filtered.map(acc => (
                                                    <button
                                                        key={acc.id}
                                                        type="button"
                                                        onMouseDown={e => { e.preventDefault(); setCategorySearch(acc.name); setSelectedAccountId(acc.id); setShowCategoryDropdown(false); }}
                                                        className="w-full text-left px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
                                                    >
                                                        {acc.name}
                                                    </button>
                                                ))}
                                                {showCreateNew && (
                                                    <button
                                                        type="button"
                                                        onMouseDown={e => { e.preventDefault(); setSelectedAccountId(null); setShowCategoryDropdown(false); }}
                                                        className="w-full text-left px-2 py-1.5 text-xs text-emerald-400 hover:bg-slate-700"
                                                    >
                                                        + 新規作成: "{categorySearch.trim()}"
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )}
                                <input
                                    type="number"
                                    value={budgetCategoryForm.amount}
                                    onChange={e => setBudgetCategoryForm({ ...budgetCategoryForm, amount: e.target.value })}
                                    placeholder="Amount"
                                    className="col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                                />
                                <button type="button" onClick={saveBudgetCategory} className="col-span-2 bg-emerald-600 hover:bg-emerald-500 text-white py-1.5 text-xs">
                                    {editingBudgetAccount ? 'Update' : 'Add'}
                                </button>
                                <button type="button" onClick={() => { setShowBudgetCategoryForm(false); setShowCategoryDropdown(false); }} className="col-span-2 bg-slate-800 hover:bg-slate-700 text-slate-300 py-1.5 text-xs">
                                    Cancel
                                </button>
                            </div>
                        </div>
                    );
                })()}

                <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                        <thead className="text-slate-500 uppercase border-b border-slate-700 bg-slate-800/50">
                            <tr>
                                <th className="px-2 py-2 text-left font-normal">Category</th>
                                <th className="px-2 py-2 text-right font-normal">Actual</th>
                                <th className="px-2 py-2 text-right font-normal">Budget</th>
                                <th className="px-2 py-2 text-right font-normal">Recurrence</th>
                                <th className="px-2 py-2 text-right font-normal">Variance</th>
                                <th className="px-2 py-2 text-right font-normal">Edit</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/70">
                            {(budgetSummary?.expense_accounts ?? []).length === 0 && (
                                <tr>
                                    <td colSpan={6} className="px-2 py-8 text-center text-slate-600 text-xs">
                                        費目が追加されていません。右上の+から追加してください。
                                    </td>
                                </tr>
                            )}
                            {(budgetSummary?.expense_accounts ?? []).map((account) => {
                                const limit = budgetEdits[account.id] ?? 0;
                                const variance = limit - (account.balance || 0);
                                const isRecurringControlled = account.source === 'recurrence';
                                return (
                                    <tr key={account.id} className="hover:bg-slate-800/30 group">
                                        <td className="px-2 py-2 text-slate-300">
                                            {account.name}
                                            {account.source === 'one_time' && account.planned_date && (
                                                <span className="ml-2 text-[9px] text-cyan-500 font-mono-nums">{account.planned_date}</span>
                                            )}
                                        </td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-slate-500">{formatCurrency(account.balance)}</td>
                                        <td className="px-2 py-2 text-right"><input type="number" step="1000" value={limit} disabled={isRecurringControlled} onChange={(event) => setBudgetEdits({ ...budgetEdits, [account.id]: Number(event.target.value) || 0 })} className={`w-24 bg-transparent border-b text-right font-mono-nums outline-none ${isRecurringControlled ? 'border-transparent text-slate-500' : 'border-slate-700 focus:border-cyan-500'}`} /></td>
                                        <td className={`px-2 py-2 text-right font-mono-nums ${(account.recurring_amount || 0) > 0 ? 'text-cyan-300' : 'text-slate-600'}`}>{(account.recurring_amount || 0) > 0 ? formatCurrency(account.recurring_amount) : '-'}</td>
                                        <td className={`px-2 py-2 text-right font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(variance)}</td>
                                        <td className="px-2 py-2 text-right flex items-center justify-end gap-2">
                                            {account.recurring_transaction_id && (
                                                <button type="button" title={account.sync_status === 'synced' ? 'Synced with recurrence' : 'Sync with recurrence'} onClick={() => syncRecurringBudgetAccount(account)} className={account.sync_status === 'synced' ? 'text-cyan-400 hover:text-cyan-200' : 'text-amber-400 hover:text-amber-200'}><RefreshCw size={12} /></button>
                                            )}
                                            {account.source === 'recurrence' && account.plan_line_id && (
                                                <button type="button" title="Remove recurrence sync" onClick={() => unlinkRecurringBudgetAccount(account)} className="text-slate-500 hover:text-amber-300"><Unlink size={12} /></button>
                                            )}
                                            {!isRecurringControlled && (
                                                <>
                                                    {account.source !== 'one_time' && (
                                                        <button type="button" title="Edit category" onClick={() => openBudgetCategoryForm(account)} className="text-slate-500 hover:text-cyan-400"><Edit2 size={12} /></button>
                                                    )}
                                                    <button type="button" title="Remove from budget" onClick={() => removeBudgetCategory(account.id, account.plan_line_id)} className="text-slate-500 hover:text-rose-400"><Trash2 size={12} /></button>
                                                </>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                            {(budgetSummary?.others_actual ?? 0) > 0 && (
                                <tr className="hover:bg-slate-800/30 opacity-60">
                                    <td className="px-2 py-2 text-slate-500 italic">others</td>
                                    <td className="px-2 py-2 text-right font-mono-nums text-slate-500">{formatCurrency(budgetSummary!.others_actual)}</td>
                                    <td colSpan={3} className="px-2 py-2 text-right text-[9px] text-slate-600">未予算費目の合計</td>
                                    <td className="px-2 py-2" />
                                </tr>
                            )}
                            <tr className="border-t border-slate-700 bg-slate-800/40">
                                <td className="px-2 py-2 text-slate-100 font-medium">Total</td>
                                <td className="px-2 py-2 text-right font-mono-nums text-slate-300">{formatCurrency(variableActualTotal)}</td>
                                <td className="px-2 py-2 text-right font-mono-nums text-slate-200">{formatCurrency(variableBudgetTotal)}</td>
                                <td className="px-2 py-2 text-right font-mono-nums text-cyan-300">{formatCurrency(variableRecurringTotal)}</td>
                                <td className={`px-2 py-2 text-right font-mono-nums ${variableVarianceTotal >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{formatCurrency(variableVarianceTotal)}</td>
                                <td className="px-2 py-2" />
                            </tr>
                        </tbody>
                    </table>
                </div>

                {renderPlanSection('Allocation Plan', ['allocation'], 'allocation', 'No asset allocations yet.', 'Allocated')}
                {renderPlanSection('Debt Plan', ['debt_payment'], 'debt_payment', 'No planned debt payments yet.')}

                <div className="mt-6">
                    <div className="flex items-center justify-between mb-3">
                        {renderTitleWithInfo('12 Month Cash Flow', 'projection')}
                        <div className="flex items-center gap-3">
                            <span className="text-xs text-slate-500 font-mono-nums">Start {formatCurrency(budgetSummary?.starting_cash)}</span>
                            <button type="button" title="Cash flow settings" onClick={() => setShowCashFlowSettings(!showCashFlowSettings)} className="text-slate-500 hover:text-cyan-400">
                                <SlidersHorizontal size={14} />
                            </button>
                        </div>
                    </div>
                    {showCashFlowSettings && (
                        <div className="mb-3 border border-slate-800 bg-slate-950/40 p-3">
                            <div className="grid grid-cols-2 gap-3 text-xs max-w-md">
                                <label className="space-y-1 text-slate-500">
                                    <span className="block text-[10px] uppercase">Start Month</span>
                                    <input
                                        type="month"
                                        value={cashFlowStartPeriod}
                                        onChange={(event) => setCashFlowStartPeriod(event.target.value || currentPeriod)}
                                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-slate-200 font-mono-nums"
                                    />
                                </label>
                                <label className="space-y-1 text-slate-500">
                                    <span className="block text-[10px] uppercase">Months</span>
                                    <input
                                        type="number"
                                        min={1}
                                        max={36}
                                        value={cashFlowMonths}
                                        onChange={(event) => setCashFlowMonths(Math.min(36, Math.max(1, Number(event.target.value) || 12)))}
                                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-slate-200 font-mono-nums"
                                    />
                                </label>
                            </div>
                        </div>
                    )}
                    <div className="grid grid-cols-2 min-[1280px]:grid-cols-4 gap-2 mb-3">
                        <div className="border border-slate-800 bg-slate-950/40 px-3 py-2">
                            <p className="text-[10px] uppercase text-slate-500">Runway</p>
                            <p className={`mt-1 font-mono-nums text-sm ${cashFlowSummary?.shortfall_month ? 'text-amber-300' : 'text-emerald-300'}`}>
                                {runwayLabel}
                            </p>
                        </div>
                        <div className="border border-slate-800 bg-slate-950/40 px-3 py-2">
                            <p className="text-[10px] uppercase text-slate-500">Lowest Cash</p>
                            <p className={`mt-1 font-mono-nums text-sm ${(cashFlowSummary?.lowest_cash ?? 0) >= 0 ? 'text-slate-200' : 'text-rose-400'}`}>
                                {formatCurrency(cashFlowSummary?.lowest_cash)}
                            </p>
                        </div>
                        <div className="border border-slate-800 bg-slate-950/40 px-3 py-2">
                            <p className="text-[10px] uppercase text-slate-500">Required Buffer</p>
                            <p className={`mt-1 font-mono-nums text-sm ${(cashFlowSummary?.required_buffer ?? 0) > 0 ? 'text-amber-300' : 'text-slate-200'}`}>
                                {formatCurrency(cashFlowSummary?.required_buffer)}
                            </p>
                        </div>
                        <div className="border border-slate-800 bg-slate-950/40 px-3 py-2">
                            <p className="text-[10px] uppercase text-slate-500">Shortfall Month</p>
                            <p className={`mt-1 font-mono-nums text-sm ${cashFlowSummary?.shortfall_month ? 'text-rose-400' : 'text-emerald-300'}`}>
                                {cashFlowSummary?.shortfall_month ?? 'None'}
                            </p>
                        </div>
                    </div>
                    <div className="overflow-x-auto border border-slate-800">
                        <table className="w-full text-[10px]">
                            <thead className="text-slate-500 uppercase border-b border-slate-700 bg-slate-800/50">
                                <tr>
                                    <th className="px-2 py-2 text-left font-normal">Month</th>
                                    <th className="px-2 py-2 text-right font-normal">Inflow</th>
                                    <th className="px-2 py-2 text-right font-normal">Expense</th>
                                    <th className="px-2 py-2 text-right font-normal">Allocation</th>
                                    <th className="px-2 py-2 text-right font-normal">Debt</th>
                                    <th className="px-2 py-2 text-right font-normal">Net</th>
                                    <th className="px-2 py-2 text-right font-normal">Ending</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/70">
                                {(budgetSummary?.cash_flow_projection ?? []).map((row) => (
                                    <tr key={row.period} className="hover:bg-slate-800/30">
                                        <td className="px-2 py-2 text-slate-300">
                                            <div className="flex items-center gap-2">
                                                <span>{row.period}</span>
                                                {(row.setup_warnings?.length ?? 0) > 0 ? (
                                                    <button
                                                        type="button"
                                                        title={(row.setup_warnings ?? []).map((warning) => `${warning.name}: ${formatCurrency(warning.amount)}`).join('\n')}
                                                        onClick={() => jumpToCashFlowPeriod(row.period)}
                                                        className="text-amber-400 hover:text-amber-200"
                                                    >
                                                        <AlertTriangle size={12} />
                                                    </button>
                                                ) : (
                                                    <span title="No recurrence warnings" className="text-slate-700">
                                                        <AlertTriangle size={12} />
                                                    </span>
                                                )}
                                                <button
                                                    type="button"
                                                    title={`Jump to ${row.period}`}
                                                    onClick={() => jumpToCashFlowPeriod(row.period)}
                                                    className="text-slate-500 hover:text-cyan-300"
                                                >
                                                    <ChevronRight size={12} />
                                                </button>
                                                <button
                                                    type="button"
                                                    title={`Sync all recurrence differences for ${row.period}`}
                                                    onClick={() => syncAllRecurrencesForPeriod(row.period)}
                                                    className={(row.setup_warnings?.length ?? 0) > 0 ? 'text-amber-400 hover:text-amber-200' : 'text-slate-500 hover:text-amber-300'}
                                                >
                                                    <RefreshCw size={12} />
                                                </button>
                                                <button
                                                    type="button"
                                                    title={`Copy current month budget to ${row.period}`}
                                                    onClick={() => copyCurrentBudgetToPeriod(row.period)}
                                                    className="text-slate-500 hover:text-emerald-300"
                                                >
                                                    <Copy size={12} />
                                                </button>
                                            </div>
                                        </td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-emerald-400">{formatCurrency(row.inflow)}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-amber-300">{formatCurrency(row.expense)}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-cyan-300">{formatCurrency(row.allocation)}</td>
                                        <td className="px-2 py-2 text-right font-mono-nums text-rose-300">{formatCurrency(row.debt)}</td>
                                        <td className={`px-2 py-2 text-right font-mono-nums ${row.net_cash >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatCurrency(row.net_cash)}</td>
                                        <td className={`px-2 py-2 text-right font-mono-nums ${row.ending_cash >= 0 ? 'text-slate-200' : 'text-rose-400'}`}>{formatCurrency(row.ending_cash)}</td>
                                    </tr>
                                ))}
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
                <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3">Capsules</h2>
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
                                    <div className="text-right"><p className="text-lg font-mono-nums text-purple-400">{formatCurrency(capsule.current_balance)}</p><p className="text-[10px] text-slate-500">{Math.round(progress)}%</p></div>
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
