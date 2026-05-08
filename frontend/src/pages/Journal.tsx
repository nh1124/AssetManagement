import { useState, useEffect, useRef } from 'react';
import {
    Trash2, Plus, Sparkles, Send, Loader2, ImagePlus, X,
    ArrowUpCircle, ArrowDownCircle, RefreshCw, Edit, SlidersHorizontal
} from 'lucide-react';
import TabPanel from '../components/TabPanel';
import SplitView from '../components/SplitView';
import {
    getRecurringTransactions,
    createRecurringTransaction, deleteRecurringTransaction, updateRecurringTransaction,
    getAccounts, createTransaction, deleteTransaction, updateTransaction, getTransactionsPage,
    analyzeWithBackend,
    getQuickTemplates, createQuickTemplate, deleteQuickTemplate, createTransactionBatch,
} from '../api';
import { useToast } from '../components/Toast';
import { useClient } from '../context/ClientContext';
import { formatCurrency as formatCurrencyWithSetting, getCurrencySymbol } from '../utils/currency';
import type { QuickTemplate, RecurringTransaction, Transaction } from '../types';

const MAIN_TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'quick', label: 'Quick' },
    { id: 'recurring', label: 'Recurring' },
    { id: 'ai', label: 'AI' },
];

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];
const FILTER_STORAGE_KEY = 'finance_journal_filters';
const PAGE_SIZE = 50;
type TransactionKind =
    | 'Income'
    | 'Expense'
    | 'Transfer'
    | 'LiabilityPayment'
    | 'Borrowing'
    | 'CreditExpense'
    | 'CreditAssetPurchase';

interface AccountItem {
    id: number;
    name: string;
    account_type: string;
    balance?: number;
}

const TRANSACTION_TYPES: Array<{
    value: TransactionKind;
    label: string;
    description: string;
    fromTypes: string[];
    toTypes: string[];
}> = [
    {
        value: 'Expense',
        label: 'Expense',
        description: 'Pay cash/bank/card asset now. Dr expense or item, Cr asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['expense', 'item'],
    },
    {
        value: 'Income',
        label: 'Income',
        description: 'Receive income into cash/bank. Dr asset, Cr income.',
        fromTypes: ['income'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'Transfer',
        label: 'Transfer',
        description: 'Move value between asset accounts. Dr destination asset, Cr source asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'Borrowing',
        label: 'Borrowing',
        description: 'Borrow loan/cash advance and increase assets. Dr asset, Cr liability.',
        fromTypes: ['liability'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'CreditExpense',
        label: 'Credit Expense',
        description: 'Buy expenses on credit. Dr expense, Cr liability.',
        fromTypes: ['liability'],
        toTypes: ['expense', 'item'],
    },
    {
        value: 'CreditAssetPurchase',
        label: 'Credit Asset Purchase',
        description: 'Buy an asset/item with credit or a loan. Dr asset or item, Cr liability.',
        fromTypes: ['liability'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'LiabilityPayment',
        label: 'Debt Repayment',
        description: 'Repay debt from cash/bank. Dr liability, Cr asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['liability'],
    },
];

const ACCOUNT_RULES = Object.fromEntries(
    TRANSACTION_TYPES.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<TransactionKind, { fromTypes: string[]; toTypes: string[] }>;

const typeDescription = (type: string) =>
    TRANSACTION_TYPES.find((option) => option.value === type)?.description ?? '';

type QuickTemplateKind =
    | 'simple_expense'
    | 'credit_expense'
    | 'expense_with_advance'
    | 'reimbursement'
    | 'transfer'
    | 'debt_payment';

const QUICK_TEMPLATE_KINDS: Array<{
    value: QuickTemplateKind;
    label: string;
    fromTypes: string[];
    toTypes: string[];
}> = [
    { value: 'simple_expense', label: 'Expense', fromTypes: ['asset', 'item', 'liability'], toTypes: ['expense', 'item'] },
    { value: 'credit_expense', label: 'Credit Expense', fromTypes: ['liability'], toTypes: ['expense', 'item'] },
    { value: 'expense_with_advance', label: 'Expense + Advance', fromTypes: ['asset', 'item', 'liability'], toTypes: ['expense', 'item'] },
    { value: 'reimbursement', label: 'Reimbursement', fromTypes: ['asset', 'item'], toTypes: ['asset', 'item'] },
    { value: 'transfer', label: 'Transfer', fromTypes: ['asset', 'item'], toTypes: ['asset', 'item'] },
    { value: 'debt_payment', label: 'Debt Payment', fromTypes: ['asset', 'item'], toTypes: ['liability'] },
];

const QUICK_KIND_RULES = Object.fromEntries(
    QUICK_TEMPLATE_KINDS.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<QuickTemplateKind, { fromTypes: string[]; toTypes: string[] }>;

const quickKindLabel = (kind: string) =>
    QUICK_TEMPLATE_KINDS.find((option) => option.value === kind)?.label ?? kind;

const defaultFilters = {
    startDate: '',
    endDate: '',
    type: '',
    q: '',
    category: '',
    amountMin: '',
    amountMax: '',
    accountId: '',
};

const loadStoredFilters = () => {
    try {
        return { ...defaultFilters, ...JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || '{}') };
    } catch {
        return defaultFilters;
    }
};

export default function Journal() {
    const [activeTab, setActiveTab] = useState(() => {
        const stored = localStorage.getItem('finance_journal_tab');
        return stored === 'quick' || stored === 'recurring' || stored === 'ai' ? stored : 'transaction';
    });
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [transactionTotal, setTransactionTotal] = useState(0);
    const [filters, setFilters] = useState(loadStoredFilters);
    const [showFilters, setShowFilters] = useState(false);
    const [editingTransactionId, setEditingTransactionId] = useState<number | null>(null);
    const [recurringItems, setRecurringItems] = useState<RecurringTransaction[]>([]);
    const [quickTemplates, setQuickTemplates] = useState<QuickTemplate[]>([]);
    const [activeQuickTray, setActiveQuickTray] = useState('');
    const [selectedQuickTemplateId, setSelectedQuickTemplateId] = useState<number | null>(null);
    const [showQuickTemplateForm, setShowQuickTemplateForm] = useState(false);
    const [accounts, setAccounts] = useState<AccountItem[]>([]);
    const [isProcessing, setIsProcessing] = useState(false);
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';
    const formatCurrency = (value: number | undefined | null) => formatCurrencyWithSetting(value, currentCurrency);

    // Manual Input State
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as TransactionKind,
        category: '',
        currency: 'JPY',
        fromAccountId: '',
        toAccountId: '',
    });

    const [quickTemplateDraft, setQuickTemplateDraft] = useState({
        tray: 'Food',
        name: '',
        template_kind: 'simple_expense' as QuickTemplateKind,
        category: '',
        default_currency: currentCurrency,
        default_from_account_id: '',
        default_to_account_id: '',
        receivable_account_id: '',
        reimbursement_account_id: '',
    });

    const [quickEntry, setQuickEntry] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        ownAmount: '',
        advanceAmount: '',
        currency: currentCurrency,
        payment_account_id: '',
        expense_account_id: '',
        receivable_account_id: '',
        reimbursement_account_id: '',
        reimbursementReceived: false,
    });

    // AI State
    const [aiInput, setAiInput] = useState('');
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const [suggestedTransactions, setSuggestedTransactions] = useState<any[]>([]);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Recurring State
    const [showAddRecurring, setShowAddRecurring] = useState(false);
    const [newRecurring, setNewRecurring] = useState({
        name: '',
        amount: '',
        currency: currentCurrency,
        type: 'Expense' as TransactionKind,
        from_account_id: '',
        to_account_id: '',
        frequency: 'Monthly',
        day_of_month: '1',
        month_of_year: '1',
        start_period: '',
        end_period: '',
        auto_post: true,
    });

    const fromAccounts = accounts.filter((a) => ACCOUNT_RULES[formData.type].fromTypes.includes(a.account_type));
    const toAccounts = accounts.filter((a) => ACCOUNT_RULES[formData.type].toTypes.includes(a.account_type));
    const recurringFromAccounts = accounts.filter((a) => ACCOUNT_RULES[newRecurring.type].fromTypes.includes(a.account_type));
    const recurringToAccounts = accounts.filter((a) => ACCOUNT_RULES[newRecurring.type].toTypes.includes(a.account_type));
    const quickDraftRules = QUICK_KIND_RULES[quickTemplateDraft.template_kind];
    const quickDraftFromAccounts = accounts.filter((a) => quickDraftRules.fromTypes.includes(a.account_type));
    const quickDraftToAccounts = accounts.filter((a) => quickDraftRules.toTypes.includes(a.account_type));
    const assetAccounts = accounts.filter((a) => ['asset', 'item'].includes(a.account_type));

    useEffect(() => {
        fetchInitialData();
        localStorage.removeItem('finance_journal_tab');
    }, []);

    useEffect(() => {
        if (!quickTemplates.length) {
            setActiveQuickTray('');
            setSelectedQuickTemplateId(null);
            return;
        }
        if (!activeQuickTray || !quickTemplates.some((template) => template.tray === activeQuickTray)) {
            setActiveQuickTray(quickTemplates[0].tray);
        }
        if (selectedQuickTemplateId && !quickTemplates.some((template) => template.id === selectedQuickTemplateId)) {
            setSelectedQuickTemplateId(null);
        }
    }, [quickTemplates, activeQuickTray, selectedQuickTemplateId]);

    useEffect(() => {
        setFormData((prev) => {
            const nextFrom = fromAccounts.find((acc) => String(acc.id) === prev.fromAccountId)
                ? prev.fromAccountId
                : (fromAccounts[0] ? String(fromAccounts[0].id) : '');
            const nextTo = toAccounts.find((acc) => String(acc.id) === prev.toAccountId)
                ? prev.toAccountId
                : (toAccounts[0] ? String(toAccounts[0].id) : '');

            if (nextFrom === prev.fromAccountId && nextTo === prev.toAccountId) {
                return prev;
            }
            return {
                ...prev,
                fromAccountId: nextFrom,
                toAccountId: nextTo,
            };
        });
    }, [formData.type, accounts.length]);

    const fetchInitialData = async () => {
        try {
            const [txPage, recs, accs, templates] = await Promise.all([
                getTransactionsPage({ ...filters, limit: PAGE_SIZE, offset: 0 }),
                getRecurringTransactions(),
                getAccounts(),
                getQuickTemplates(),
            ]);
            setTransactions(txPage.items);
            setTransactionTotal(txPage.total);
            setRecurringItems(recs);
            setAccounts(accs);
            setQuickTemplates(templates);
        } catch (error) {
            console.error('Failed to fetch journal data:', error);
            showToast('Failed to load data', 'error');
        }
    };

    const fetchQuickTemplatesOnly = async () => {
        try {
            const templates = await getQuickTemplates();
            setQuickTemplates(templates);
        } catch (error) {
            console.error('Failed to update quick templates:', error);
            showToast('Failed to load quick templates', 'error');
        }
    };

    const fetchTransactionsOnly = async (nextFilters = filters, append = false) => {
        try {
            const txPage = await getTransactionsPage({
                ...nextFilters,
                limit: PAGE_SIZE,
                offset: append ? transactions.length : 0,
            });
            setTransactions((prev) => append ? [...prev, ...txPage.items] : txPage.items);
            setTransactionTotal(txPage.total);
        } catch (error) {
            console.error('Failed to update transactions:', error);
        }
    };

    const applyFilters = (nextFilters = filters) => {
        localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(nextFilters));
        setFilters(nextFilters);
        fetchTransactionsOnly(nextFilters, false);
    };

    const setPresetRange = (preset: 'today' | 'week' | 'month' | '30d') => {
        const end = new Date();
        const start = new Date();
        if (preset === 'week') start.setDate(end.getDate() - 6);
        if (preset === 'month') start.setDate(1);
        if (preset === '30d') start.setDate(end.getDate() - 29);
        const next = {
            ...filters,
            startDate: start.toISOString().slice(0, 10),
            endDate: end.toISOString().slice(0, 10),
        };
        applyFilters(next);
    };

    const clearFilters = () => {
        localStorage.removeItem(FILTER_STORAGE_KEY);
        setFilters(defaultFilters);
        fetchTransactionsOnly(defaultFilters, false);
    };

    const accountById = (id: number | string | null | undefined) => {
        if (id === null || id === undefined || id === '') return undefined;
        return accounts.find((account) => account.id === Number(id));
    };

    const configAccountId = (template: QuickTemplate | undefined, key: string) => {
        const value = template?.config?.[key];
        if (typeof value === 'number') return value;
        if (typeof value === 'string' && value) return Number(value);
        return undefined;
    };

    const selectedQuickTemplate = selectedQuickTemplateId
        ? quickTemplates.find((template) => template.id === selectedQuickTemplateId)
        : undefined;

    const quickTrays = Array.from(new Set(quickTemplates.map((template) => template.tray)));
    const visibleQuickTemplates = quickTemplates.filter((template) => !activeQuickTray || template.tray === activeQuickTray);

    const selectQuickTemplate = (template: QuickTemplate) => {
        setSelectedQuickTemplateId(template.id);
        setQuickEntry((prev) => ({
            ...prev,
            description: prev.description || template.name,
            currency: template.default_currency || currentCurrency,
            payment_account_id: template.default_from_account_id ? String(template.default_from_account_id) : '',
            expense_account_id: template.default_to_account_id ? String(template.default_to_account_id) : '',
            receivable_account_id: configAccountId(template, 'receivable_account_id')
                ? String(configAccountId(template, 'receivable_account_id'))
                : '',
            reimbursement_account_id: configAccountId(template, 'reimbursement_account_id')
                ? String(configAccountId(template, 'reimbursement_account_id'))
                : '',
        }));
    };

    const resetQuickEntryAmounts = () => {
        setQuickEntry((prev) => ({
            ...prev,
            amount: '',
            ownAmount: '',
            advanceAmount: '',
            description: selectedQuickTemplate?.name || '',
            reimbursementReceived: false,
        }));
    };

    const buildQuickTransactions = (): { transactions: Array<Omit<Transaction, 'id'>>; error?: string } => {
        if (!selectedQuickTemplate) return { transactions: [], error: 'Select a quick template' };
        const kind = selectedQuickTemplate.template_kind as QuickTemplateKind;
        const amount = Number(quickEntry.amount || 0);
        const ownAmount = Number(quickEntry.ownAmount || 0);
        const advanceAmount = Number(quickEntry.advanceAmount || 0);
        const paymentAccount = accountById(quickEntry.payment_account_id);
        const expenseAccount = accountById(quickEntry.expense_account_id);
        const receivableAccount = accountById(quickEntry.receivable_account_id || quickEntry.payment_account_id);
        const reimbursementAccount = accountById(quickEntry.reimbursement_account_id || quickEntry.expense_account_id);
        const description = quickEntry.description.trim() || selectedQuickTemplate.name;
        const category = selectedQuickTemplate.category || expenseAccount?.name || selectedQuickTemplate.tray;
        const base = {
            date: quickEntry.date,
            currency: quickEntry.currency || selectedQuickTemplate.default_currency || currentCurrency,
        };

        if (!amount || amount <= 0) return { transactions: [], error: 'Amount is required' };

        if (kind === 'reimbursement') {
            if (!receivableAccount || !reimbursementAccount) return { transactions: [], error: 'Receivable and deposit accounts are required' };
            return {
                transactions: [{
                    ...base,
                    description,
                    amount,
                    type: 'Transfer',
                    category: selectedQuickTemplate.category || 'reimbursement',
                    from_account_id: receivableAccount.id,
                    to_account_id: reimbursementAccount.id,
                }],
            };
        }

        if (kind === 'transfer') {
            if (!paymentAccount || !expenseAccount) return { transactions: [], error: 'From and to accounts are required' };
            return {
                transactions: [{
                    ...base,
                    description,
                    amount,
                    type: 'Transfer',
                    category: selectedQuickTemplate.category || 'transfer',
                    from_account_id: paymentAccount.id,
                    to_account_id: expenseAccount.id,
                }],
            };
        }

        if (kind === 'debt_payment') {
            if (!paymentAccount || !expenseAccount) return { transactions: [], error: 'Payment and debt accounts are required' };
            return {
                transactions: [{
                    ...base,
                    description,
                    amount,
                    type: 'LiabilityPayment',
                    category: selectedQuickTemplate.category || expenseAccount.name,
                    from_account_id: paymentAccount.id,
                    to_account_id: expenseAccount.id,
                }],
            };
        }

        if (!paymentAccount || !expenseAccount) return { transactions: [], error: 'Payment and expense accounts are required' };
        const isCreditPayment = paymentAccount.account_type === 'liability';

        if (kind === 'expense_with_advance') {
            const resolvedAdvance = advanceAmount > 0 ? advanceAmount : Math.max(0, amount - ownAmount);
            const resolvedOwn = ownAmount > 0 ? ownAmount : Math.max(0, amount - resolvedAdvance);
            if (resolvedOwn + resolvedAdvance <= 0) return { transactions: [], error: 'Own share or advance amount is required' };
            if (resolvedAdvance > 0 && !receivableAccount) return { transactions: [], error: 'Receivable account is required' };

            const transactions: Array<Omit<Transaction, 'id'>> = [];
            if (resolvedOwn > 0) {
                transactions.push({
                    ...base,
                    description: `${description} own share`,
                    amount: resolvedOwn,
                    type: isCreditPayment ? 'CreditExpense' : 'Expense',
                    category,
                    from_account_id: paymentAccount.id,
                    to_account_id: expenseAccount.id,
                });
            }
            if (resolvedAdvance > 0 && receivableAccount) {
                transactions.push({
                    ...base,
                    description: `${description} advance`,
                    amount: resolvedAdvance,
                    type: isCreditPayment ? 'CreditAssetPurchase' : 'Transfer',
                    category: 'advance',
                    from_account_id: paymentAccount.id,
                    to_account_id: receivableAccount.id,
                });
            }
            if (quickEntry.reimbursementReceived && resolvedAdvance > 0) {
                if (!receivableAccount || !reimbursementAccount) return { transactions: [], error: 'Deposit account is required for reimbursement' };
                transactions.push({
                    ...base,
                    description: `${description} reimbursement`,
                    amount: resolvedAdvance,
                    type: 'Transfer',
                    category: 'reimbursement',
                    from_account_id: receivableAccount.id,
                    to_account_id: reimbursementAccount.id,
                });
            }
            return { transactions };
        }

        return {
            transactions: [{
                ...base,
                description,
                amount,
                type: kind === 'credit_expense' || isCreditPayment ? 'CreditExpense' : 'Expense',
                category,
                from_account_id: paymentAccount.id,
                to_account_id: expenseAccount.id,
            }],
        };
    };

    const quickPreview = buildQuickTransactions();

    const handleCreateQuickTemplate = async () => {
        if (!quickTemplateDraft.tray.trim() || !quickTemplateDraft.name.trim()) {
            showToast('Tray and template name are required', 'error');
            return;
        }
        try {
            const template = await createQuickTemplate({
                tray: quickTemplateDraft.tray.trim(),
                name: quickTemplateDraft.name.trim(),
                template_kind: quickTemplateDraft.template_kind,
                description: null,
                category: quickTemplateDraft.category.trim() || null,
                default_currency: quickTemplateDraft.default_currency || currentCurrency,
                default_from_account_id: quickTemplateDraft.default_from_account_id ? Number(quickTemplateDraft.default_from_account_id) : null,
                default_to_account_id: quickTemplateDraft.default_to_account_id ? Number(quickTemplateDraft.default_to_account_id) : null,
                config: {
                    receivable_account_id: quickTemplateDraft.receivable_account_id ? Number(quickTemplateDraft.receivable_account_id) : null,
                    reimbursement_account_id: quickTemplateDraft.reimbursement_account_id ? Number(quickTemplateDraft.reimbursement_account_id) : null,
                },
                sort_order: quickTemplates.length,
                is_active: true,
            });
            showToast('Quick template created', 'success');
            setShowQuickTemplateForm(false);
            setQuickTemplateDraft({
                tray: template.tray,
                name: '',
                template_kind: 'simple_expense',
                category: '',
                default_currency: currentCurrency,
                default_from_account_id: '',
                default_to_account_id: '',
                receivable_account_id: '',
                reimbursement_account_id: '',
            });
            await fetchQuickTemplatesOnly();
            setActiveQuickTray(template.tray);
            setSelectedQuickTemplateId(template.id);
            selectQuickTemplate(template);
        } catch (error) {
            console.error(error);
            showToast('Failed to create quick template', 'error');
        }
    };

    const handleDeleteQuickTemplate = async (id: number) => {
        try {
            await deleteQuickTemplate(id);
            showToast('Quick template deleted', 'info');
            await fetchQuickTemplatesOnly();
        } catch (error) {
            console.error(error);
            showToast('Failed to delete quick template', 'error');
        }
    };

    const handlePostQuickBatch = async () => {
        if (quickPreview.error || quickPreview.transactions.length === 0) {
            showToast(quickPreview.error || 'No transactions to post', 'error');
            return;
        }
        setIsProcessing(true);
        try {
            await createTransactionBatch({
                quick_template_id: selectedQuickTemplate?.id ?? null,
                label: quickEntry.description || selectedQuickTemplate?.name || 'Quick entry',
                source: 'quick',
                input_payload: {
                    template_kind: selectedQuickTemplate?.template_kind,
                    tray: selectedQuickTemplate?.tray,
                    entry: quickEntry,
                },
                transactions: quickPreview.transactions,
            });
            showToast(`Posted ${quickPreview.transactions.length} transactions`, 'success');
            resetQuickEntryAmounts();
            fetchTransactionsOnly();
        } catch (error) {
            console.error(error);
            showToast('Failed to post quick transactions', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleRecordSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!formData.amount) return;
        setIsProcessing(true);
        try {
            const fromAccountId = formData.fromAccountId ? parseInt(formData.fromAccountId, 10) : undefined;
            const toAccountId = formData.toAccountId ? parseInt(formData.toAccountId, 10) : undefined;
            const toAccount = toAccounts.find((acc) => acc.id === toAccountId);

            const payload = {
                date: formData.date,
                description: formData.description,
                amount: parseFloat(formData.amount),
                type: formData.type,
                category: toAccount?.name || formData.category || '',
                currency: formData.currency,
                from_account_id: fromAccountId,
                to_account_id: toAccountId,
            };
            if (editingTransactionId) {
                await updateTransaction(editingTransactionId, payload);
                showToast('Transaction updated', 'success');
            } else {
                await createTransaction(payload);
                showToast('Record saved', 'success');
            }
            setEditingTransactionId(null);
            setFormData({ ...formData, description: '', amount: '', category: '' });
            fetchTransactionsOnly();
        } catch (error) {
            showToast('Failed to save record', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleAiSubmit = async () => {
        if (!aiInput.trim() && !selectedImage) return;
        setIsProcessing(true);
        try {
            const parts: any[] = [];
            if (aiInput) parts.push({ text: aiInput });
            if (selectedImage) {
                const base64Data = selectedImage.split(',')[1];
                const mimeType = selectedImage.split(';')[0].split(':')[1];
                parts.push({ inline_data: { mime_type: mimeType, data: base64Data } });
            }
            const results = await analyzeWithBackend({ parts });
            if (Array.isArray(results)) setSuggestedTransactions(results);
        } catch (error) {
            showToast('AI analysis failed', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleConfirmSuggestions = async () => {
        setIsProcessing(true);
        try {
            let processedCount = 0;
            const resolveAccountId = (
                accountName: string | undefined,
                candidateTypes: string[],
                fallbackToFirst: boolean
            ): number | undefined => {
                if (accountName) {
                    const matched = accounts.find(
                        (acc) =>
                            candidateTypes.includes(acc.account_type) &&
                            acc.name.toLowerCase() === accountName.toLowerCase()
                    );
                    if (matched) return matched.id;
                }
                if (!fallbackToFirst) return undefined;
                const first = accounts.find((acc) => candidateTypes.includes(acc.account_type));
                return first?.id;
            };

            for (const suggestion of suggestedTransactions) {
                const txType = (suggestion.type as TransactionKind) || 'Expense';
                const rules = ACCOUNT_RULES[txType];
                if (suggestion.is_recurring) {
                    // Map account names to IDs for recurring transaction
                    const fromAccountId = resolveAccountId(suggestion.from_account, rules.fromTypes, true);
                    const toAccountId = resolveAccountId(suggestion.to_account, rules.toTypes, true);

                    await createRecurringTransaction({
                        name: suggestion.description,
                        amount: suggestion.amount,
                        currency: suggestion.currency || currentCurrency,
                        type: txType,
                        from_account_id: fromAccountId ?? null,
                        to_account_id: toAccountId ?? null,
                        frequency: suggestion.frequency || 'Monthly',
                        day_of_month: suggestion.day_of_month || 1,
                        month_of_year: suggestion.frequency === 'Yearly' ? (suggestion.month_of_year || 1) : null,
                    });
                } else {
                    const fromAccountId = resolveAccountId(suggestion.from_account, rules.fromTypes, true);
                    const toAccountId = resolveAccountId(suggestion.to_account, rules.toTypes, true);
                    const toAccount = accounts.find((acc) => acc.id === toAccountId);

                    await createTransaction({
                        date: suggestion.date || formData.date,
                        description: suggestion.description,
                        amount: suggestion.amount,
                        type: txType,
                        category: suggestion.category || toAccount?.name || '',
                        currency: suggestion.currency || 'JPY',
                        from_account_id: fromAccountId,
                        to_account_id: toAccountId,
                    });
                }
                processedCount++;
            }
            showToast(`Saved ${processedCount} records`, 'success');
            setSuggestedTransactions([]);
            setAiInput('');
            setSelectedImage(null);
            fetchTransactionsOnly();
            // Refresh recurring items as well
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (error) {
            console.error(error);
            showToast('Failed to confirm some records', 'error');
        } finally {
            setIsProcessing(false);
        }
    };

    const handleDeleteTransaction = async (id: number) => {
        try {
            await deleteTransaction(id);
            showToast('Transaction deleted', 'info');
            fetchTransactionsOnly();
        } catch (error) {
            showToast('Failed to delete transaction', 'error');
        }
    };

    const handleEditTransaction = (tx: Transaction) => {
        setActiveTab('transaction');
        setEditingTransactionId(tx.id);
        setFormData({
            date: tx.date,
            description: tx.description,
            amount: String(tx.amount),
            type: tx.type,
            category: tx.category || '',
            currency: tx.currency || 'JPY',
            fromAccountId: tx.from_account_id ? String(tx.from_account_id) : '',
            toAccountId: tx.to_account_id ? String(tx.to_account_id) : '',
        });
    };

    const cancelEditTransaction = () => {
        setEditingTransactionId(null);
        setFormData({
            date: new Date().toISOString().split('T')[0],
            description: '',
            amount: '',
            type: 'Expense',
            category: '',
            currency: 'JPY',
            fromAccountId: '',
            toAccountId: '',
        });
    };

    const [editingRecurringId, setEditingRecurringId] = useState<number | null>(null); // State for editing

    const handleAddRecurring = async () => {
        if (!newRecurring.name || !newRecurring.amount) return;
        try {
            const payload = {
                name: newRecurring.name,
                amount: parseFloat(newRecurring.amount),
                currency: newRecurring.currency,
                type: newRecurring.type,
                from_account_id: parseInt(newRecurring.from_account_id) || null,
                to_account_id: parseInt(newRecurring.to_account_id) || null,
                frequency: newRecurring.frequency,
                day_of_month: parseInt(newRecurring.day_of_month),
                month_of_year: newRecurring.frequency === 'Yearly' ? parseInt(newRecurring.month_of_year) : null,
                start_period: newRecurring.start_period || null,
                end_period: newRecurring.end_period || null,
                auto_post: newRecurring.auto_post,
            };

            if (editingRecurringId) {
                // Update existing rule
                await updateRecurringTransaction(editingRecurringId, payload);
                showToast('Recurring payment updated', 'success');
            } else {
                // Create new rule
                await createRecurringTransaction(payload);
                showToast('Recurring payment added', 'success');
            }

            setShowAddRecurring(false);
            setEditingRecurringId(null);
            setNewRecurring({
                name: '', amount: '', type: 'Expense', from_account_id: '',
                currency: currentCurrency,
                to_account_id: '', frequency: 'Monthly', day_of_month: '1', month_of_year: '1',
                start_period: '', end_period: '', auto_post: true,
            });
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (err) {
            showToast('Failed to save rule', 'error');
        }
    };

    const handleEditRecurring = (item: any) => {
        setActiveTab('recurring');
        setNewRecurring({
            name: item.name,
            amount: item.amount.toString(),
            currency: item.currency || currentCurrency,
            type: item.type as TransactionKind,
            from_account_id: item.from_account_id ? item.from_account_id.toString() : '',
            to_account_id: item.to_account_id ? item.to_account_id.toString() : '',
            frequency: item.frequency,
            day_of_month: item.day_of_month.toString(),
            month_of_year: item.month_of_year ? item.month_of_year.toString() : '1',
            start_period: item.start_period || '',
            end_period: item.end_period || '',
            auto_post: item.auto_post ?? true,
        });
        setEditingRecurringId(item.id);
        setShowAddRecurring(true);
    };

    const handleDeleteRecurring = async (id: number) => {
        try {
            await deleteRecurringTransaction(id);
            showToast('Rule deleted', 'info');
            const recs = await getRecurringTransactions();
            setRecurringItems(recs);
        } catch (err) {
            showToast('Failed to delete rule', 'error');
        }
    };

    const loadedIncome = transactions
        .filter((tx) => tx.type === 'Income')
        .reduce((sum, tx) => sum + tx.amount, 0);
    const loadedOutflow = transactions
        .filter((tx) => tx.type !== 'Income')
        .reduce((sum, tx) => sum + tx.amount, 0);
    const loadedNet = loadedIncome - loadedOutflow;
    const loadedAverage = transactions.length
        ? transactions.reduce((sum, tx) => sum + tx.amount, 0) / transactions.length
        : 0;

    const leftPane = (
        <TabPanel tabs={MAIN_TABS} activeTab={activeTab} onTabChange={setActiveTab}>
            <div className="py-2">
                {activeTab === 'transaction' && (
                    <form onSubmit={handleRecordSubmit} className="space-y-4 pt-2">
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                                <input
                                    type="date"
                                    value={formData.date}
                                    onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Type</label>
                                <select
                                    value={formData.type}
                                    onChange={(e) => setFormData({ ...formData, type: e.target.value as TransactionKind })}
                                    title={typeDescription(formData.type)}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    {TRANSACTION_TYPES.map((option) => (
                                        <option key={option.value} value={option.value} title={option.description}>
                                            {option.label}
                                        </option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description</label>
                            <input
                                type="text"
                                placeholder="What was this for?"
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                                <input
                                    type="number"
                                    placeholder="0"
                                    value={formData.amount}
                                    onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Currency</label>
                                <select
                                    value={formData.currency}
                                    onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    {CURRENCIES.map((c) => (
                                        <option key={c} value={c}>{c}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                                <select
                                    value={formData.fromAccountId}
                                    onChange={(e) => setFormData({ ...formData, fromAccountId: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    {fromAccounts.map((a) => (
                                        <option key={a.id} value={a.id}>{a.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To Account</label>
                                <select
                                    value={formData.toAccountId}
                                    onChange={(e) => {
                                        const newToAccount = toAccounts.find((a) => String(a.id) === e.target.value);
                                        setFormData({ ...formData, toAccountId: e.target.value, category: newToAccount?.name || formData.category });
                                    }}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    {toAccounts.map((a) => (
                                        <option key={a.id} value={a.id}>{a.name}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="flex gap-2">
                            <button
                                type="submit"
                                disabled={isProcessing}
                                className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors disabled:opacity-50"
                            >
                                {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                {editingTransactionId ? 'Update Transaction' : 'Save Transaction'}
                            </button>
                            {editingTransactionId && (
                                <button
                                    type="button"
                                    onClick={cancelEditTransaction}
                                    className="px-4 bg-slate-800 hover:bg-slate-700 text-slate-300 py-2 text-xs font-medium"
                                >
                                    Cancel
                                </button>
                            )}
                        </div>
                    </form>
                )}

                {activeTab === 'quick' && (
                    <div className="space-y-4 pt-2">
                        <div className="flex items-center justify-between">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Quick Trays</h3>
                            <button
                                type="button"
                                onClick={() => setShowQuickTemplateForm((value) => !value)}
                                className="p-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded"
                                aria-label="Add quick template"
                                title="Add quick template"
                            >
                                <Plus size={14} />
                            </button>
                        </div>

                        {showQuickTemplateForm && (
                            <div className="border border-emerald-800/50 bg-emerald-900/10 p-3 space-y-3">
                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Tray</label>
                                        <input
                                            type="text"
                                            value={quickTemplateDraft.tray}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, tray: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Name</label>
                                        <input
                                            type="text"
                                            value={quickTemplateDraft.name}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, name: e.target.value })}
                                            placeholder="Lunch"
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Kind</label>
                                        <select
                                            value={quickTemplateDraft.template_kind}
                                            onChange={(e) => setQuickTemplateDraft({
                                                ...quickTemplateDraft,
                                                template_kind: e.target.value as QuickTemplateKind,
                                                default_from_account_id: '',
                                                default_to_account_id: '',
                                            })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        >
                                            {QUICK_TEMPLATE_KINDS.map((option) => (
                                                <option key={option.value} value={option.value}>{option.label}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Currency</label>
                                        <select
                                            value={quickTemplateDraft.default_currency}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, default_currency: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        >
                                            {CURRENCIES.map((currency) => (
                                                <option key={currency} value={currency}>{currency}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From</label>
                                        <select
                                            value={quickTemplateDraft.default_from_account_id}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, default_from_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {quickDraftFromAccounts.map((account) => (
                                                <option key={account.id} value={account.id}>{account.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To</label>
                                        <select
                                            value={quickTemplateDraft.default_to_account_id}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, default_to_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {quickDraftToAccounts.map((account) => (
                                                <option key={account.id} value={account.id}>{account.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</label>
                                        <input
                                            type="text"
                                            value={quickTemplateDraft.category}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, category: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Receivable</label>
                                        <select
                                            value={quickTemplateDraft.receivable_account_id}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, receivable_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {assetAccounts.map((account) => (
                                                <option key={account.id} value={account.id}>{account.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Reimbursement Deposit</label>
                                        <select
                                            value={quickTemplateDraft.reimbursement_account_id}
                                            onChange={(e) => setQuickTemplateDraft({ ...quickTemplateDraft, reimbursement_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {assetAccounts.map((account) => (
                                                <option key={account.id} value={account.id}>{account.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={handleCreateQuickTemplate}
                                        className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-2 text-xs font-bold"
                                    >
                                        Create Template
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setShowQuickTemplateForm(false)}
                                        className="px-4 bg-slate-800 hover:bg-slate-700 py-2 text-xs font-bold text-slate-400"
                                    >
                                        Cancel
                                    </button>
                                </div>
                            </div>
                        )}

                        {quickTemplates.length > 0 ? (
                            <>
                                <div className="flex gap-1 overflow-x-auto pb-1">
                                    {quickTrays.map((tray) => (
                                        <button
                                            type="button"
                                            key={tray}
                                            onClick={() => setActiveQuickTray(tray)}
                                            className={`px-3 py-1.5 text-xs border whitespace-nowrap ${activeQuickTray === tray ? 'border-emerald-600 bg-emerald-950/40 text-emerald-300' : 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'}`}
                                        >
                                            {tray}
                                        </button>
                                    ))}
                                </div>
                                <div className="grid grid-cols-2 gap-2">
                                    {visibleQuickTemplates.map((template) => (
                                        <button
                                            type="button"
                                            key={template.id}
                                            onClick={() => selectQuickTemplate(template)}
                                            className={`min-h-16 border px-3 py-2 text-left transition-colors ${selectedQuickTemplateId === template.id ? 'border-emerald-500 bg-emerald-950/30' : 'border-slate-700 bg-slate-800/50 hover:border-slate-500'}`}
                                        >
                                            <span className="block text-xs font-medium text-white truncate">{template.name}</span>
                                            <span className="block text-[10px] text-slate-500 truncate">{quickKindLabel(template.template_kind)}</span>
                                            <span className="block text-[10px] text-slate-600 truncate">
                                                {template.default_from_account_name || '...'} → {template.default_to_account_name || '...'}
                                            </span>
                                        </button>
                                    ))}
                                </div>
                            </>
                        ) : (
                            <div className="border border-dashed border-slate-700 bg-slate-900/40 p-4 text-center">
                                <p className="text-xs text-slate-500">No quick templates yet</p>
                                <button
                                    type="button"
                                    onClick={() => setShowQuickTemplateForm(true)}
                                    className="mt-3 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold"
                                >
                                    New Template
                                </button>
                            </div>
                        )}

                        {selectedQuickTemplate && (
                            <div className="border border-slate-700 bg-slate-900/60 p-3 space-y-3">
                                <div className="flex items-center justify-between gap-2 border-b border-slate-800 pb-2">
                                    <div>
                                        <p className="text-xs font-bold text-white">{selectedQuickTemplate.name}</p>
                                        <p className="text-[10px] text-slate-500">{selectedQuickTemplate.tray} / {quickKindLabel(selectedQuickTemplate.template_kind)}</p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => handleDeleteQuickTemplate(selectedQuickTemplate.id)}
                                        className="p-1 text-slate-500 hover:text-rose-400"
                                        aria-label="Delete quick template"
                                        title="Delete quick template"
                                    >
                                        <Trash2 size={13} />
                                    </button>
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                                        <input
                                            type="date"
                                            value={quickEntry.date}
                                            onChange={(e) => setQuickEntry({ ...quickEntry, date: e.target.value })}
                                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Currency</label>
                                        <select
                                            value={quickEntry.currency}
                                            onChange={(e) => setQuickEntry({ ...quickEntry, currency: e.target.value })}
                                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                        >
                                            {CURRENCIES.map((currency) => (
                                                <option key={currency} value={currency}>{currency}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description</label>
                                        <input
                                            type="text"
                                            value={quickEntry.description}
                                            onChange={(e) => setQuickEntry({ ...quickEntry, description: e.target.value })}
                                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                                        <input
                                            type="number"
                                            value={quickEntry.amount}
                                            onChange={(e) => setQuickEntry({ ...quickEntry, amount: e.target.value })}
                                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                        />
                                    </div>
                                    {(selectedQuickTemplate.template_kind === 'expense_with_advance') && (
                                        <>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Own Share</label>
                                                <input
                                                    type="number"
                                                    value={quickEntry.ownAmount}
                                                    onChange={(e) => setQuickEntry({ ...quickEntry, ownAmount: e.target.value })}
                                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Advance</label>
                                                <input
                                                    type="number"
                                                    value={quickEntry.advanceAmount}
                                                    onChange={(e) => setQuickEntry({ ...quickEntry, advanceAmount: e.target.value })}
                                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                                />
                                            </div>
                                        </>
                                    )}
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                                            {selectedQuickTemplate.template_kind === 'reimbursement' ? 'Receivable' : 'From'}
                                        </label>
                                        <select
                                            value={quickEntry.payment_account_id}
                                            onChange={(e) => setQuickEntry({ ...quickEntry, payment_account_id: e.target.value })}
                                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                        >
                                            <option value="">Select...</option>
                                            {accounts
                                                .filter((account) => QUICK_KIND_RULES[selectedQuickTemplate.template_kind as QuickTemplateKind].fromTypes.includes(account.account_type))
                                                .map((account) => (
                                                    <option key={account.id} value={account.id}>{account.name}</option>
                                                ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                                            {selectedQuickTemplate.template_kind === 'debt_payment' ? 'Debt' : selectedQuickTemplate.template_kind === 'transfer' || selectedQuickTemplate.template_kind === 'reimbursement' ? 'To' : 'Expense'}
                                        </label>
                                        <select
                                            value={quickEntry.expense_account_id}
                                            onChange={(e) => setQuickEntry({ ...quickEntry, expense_account_id: e.target.value })}
                                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                        >
                                            <option value="">Select...</option>
                                            {accounts
                                                .filter((account) => QUICK_KIND_RULES[selectedQuickTemplate.template_kind as QuickTemplateKind].toTypes.includes(account.account_type))
                                                .map((account) => (
                                                    <option key={account.id} value={account.id}>{account.name}</option>
                                                ))}
                                        </select>
                                    </div>
                                    {selectedQuickTemplate.template_kind === 'expense_with_advance' && (
                                        <>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Receivable</label>
                                                <select
                                                    value={quickEntry.receivable_account_id}
                                                    onChange={(e) => setQuickEntry({ ...quickEntry, receivable_account_id: e.target.value })}
                                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                                >
                                                    <option value="">Select...</option>
                                                    {assetAccounts.map((account) => (
                                                        <option key={account.id} value={account.id}>{account.name}</option>
                                                    ))}
                                                </select>
                                            </div>
                                            <label className="flex items-end gap-2 text-xs text-slate-300 pb-1">
                                                <input
                                                    type="checkbox"
                                                    checked={quickEntry.reimbursementReceived}
                                                    onChange={(e) => setQuickEntry({ ...quickEntry, reimbursementReceived: e.target.checked })}
                                                    className="accent-emerald-500"
                                                />
                                                Reimbursed
                                            </label>
                                            {quickEntry.reimbursementReceived && (
                                                <div className="col-span-2">
                                                    <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Deposit Account</label>
                                                    <select
                                                        value={quickEntry.reimbursement_account_id}
                                                        onChange={(e) => setQuickEntry({ ...quickEntry, reimbursement_account_id: e.target.value })}
                                                        className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                                                    >
                                                        <option value="">Select...</option>
                                                        {assetAccounts.map((account) => (
                                                            <option key={account.id} value={account.id}>{account.name}</option>
                                                        ))}
                                                    </select>
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>

                                <div className="space-y-2">
                                    <h4 className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Preview</h4>
                                    {quickPreview.transactions.length > 0 ? (
                                        <div className="space-y-1">
                                            {quickPreview.transactions.map((tx, index) => (
                                                <div key={`${tx.description}-${index}`} className="flex items-center justify-between gap-2 bg-slate-800/50 border border-slate-700 px-2 py-1.5">
                                                    <div className="min-w-0">
                                                        <p className="text-[11px] text-slate-200 truncate">{tx.description}</p>
                                                        <p className="text-[10px] text-slate-500 truncate">
                                                            {tx.type} / {accountById(tx.from_account_id)?.name || '...'} → {accountById(tx.to_account_id)?.name || '...'}
                                                        </p>
                                                    </div>
                                                    <span className="text-[11px] font-mono-nums text-emerald-300 whitespace-nowrap">
                                                        {formatCurrencyWithSetting(tx.amount, tx.currency || currentCurrency)}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <p className="text-xs text-slate-600 border border-dashed border-slate-800 px-2 py-3 text-center">{quickPreview.error || 'No preview'}</p>
                                    )}
                                </div>

                                <button
                                    type="button"
                                    onClick={handlePostQuickBatch}
                                    disabled={isProcessing || quickPreview.transactions.length === 0}
                                    className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white py-2.5 flex items-center justify-center gap-2 text-xs font-bold transition-colors"
                                >
                                    {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                    Post {quickPreview.transactions.length || ''} Transactions
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'ai' && (
                    <div className="space-y-4 pt-2">
                        {!suggestedTransactions.length ? (
                            <>
                                <div className="border border-amber-800/50 bg-amber-900/10 p-2 text-xs flex items-center gap-2 text-amber-400">
                                    <Sparkles size={12} /> Multi-record extraction from text or images
                                </div>
                                <textarea
                                    placeholder="e.g., Lunch 1200 yen and Grocery 3500 yen"
                                    value={aiInput}
                                    onChange={(e) => setAiInput(e.target.value)}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500 h-24 resize-none"
                                />
                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={() => fileInputRef.current?.click()}
                                        className="flex-1 bg-slate-800 border border-dashed border-slate-600 hover:border-amber-500 py-3 flex items-center justify-center gap-2 text-xs text-slate-400 hover:text-amber-400 transition-colors"
                                    >
                                        <ImagePlus size={16} /> {selectedImage ? 'Change Image' : 'Upload Image'}
                                    </button>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        accept="image/*"
                                        onChange={(e) => {
                                            const file = e.target.files?.[0];
                                            if (file) {
                                                const reader = new FileReader();
                                                reader.onloadend = () => setSelectedImage(reader.result as string);
                                                reader.readAsDataURL(file);
                                            }
                                        }}
                                        className="hidden"
                                    />
                                </div>
                                {selectedImage && (
                                    <div className="relative">
                                        <img src={selectedImage} alt="Preview" className="w-full h-32 object-cover border border-slate-700" />
                                        <button
                                            type="button"
                                            onClick={() => setSelectedImage(null)}
                                            className="absolute top-1 right-1 bg-slate-900/80 p-1 text-slate-400 hover:text-white"
                                            aria-label="Remove selected image"
                                            title="Remove selected image"
                                        >
                                            <X size={14} />
                                        </button>
                                    </div>
                                )}
                                <button
                                    onClick={handleAiSubmit}
                                    disabled={isProcessing || (!aiInput.trim() && !selectedImage)}
                                    className="w-full bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white py-2.5 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                                >
                                    {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                                    {isProcessing ? 'Thinking...' : 'Extract Records'}
                                </button>
                            </>
                        ) : (
                            <div className="space-y-3">
                                <div className="flex justify-between items-center">
                                    <h3 className="text-[10px] text-amber-500 font-bold uppercase tracking-widest">Suggestions</h3>
                                    <button onClick={() => setSuggestedTransactions([])} className="text-[10px] text-slate-500 hover:text-white">Discard</button>
                                </div>
                                <div className="space-y-2 max-h-60 overflow-auto pr-1">
                                    {suggestedTransactions.map((st, idx) => (
                                        <div key={idx} className="bg-slate-800/50 border border-slate-700 p-2 relative group">
                                            <div className="flex justify-between items-start">
                                                <p className="text-xs font-medium text-white">{st.description}</p>
                                                {st.is_recurring && (
                                                    <span className="text-[8px] bg-cyan-900/50 text-cyan-400 px-1 rounded border border-cyan-800/50">Recurring</span>
                                                )}
                                            </div>
                                            <p className="text-[10px] text-slate-500">
                                                {st.is_recurring
                                                    ? `${st.frequency} (Day ${st.day_of_month})`
                                                    : st.date}
                                                / {st.category} / {formatCurrency(st.amount)}
                                            </p>
                                            <button
                                                type="button"
                                                onClick={() => setSuggestedTransactions(prev => prev.filter((_, i) => i !== idx))}
                                                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-500"
                                                aria-label="Remove suggestion"
                                                title="Remove suggestion"
                                            >
                                                <X size={10} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                                <button onClick={handleConfirmSuggestions} disabled={isProcessing} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-2 text-xs font-bold transition-all">
                                    {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                    Confirm & Save All ({suggestedTransactions.length})
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'recurring' && (
                    <div className="space-y-3 pt-2">
                        <div className="flex items-center justify-between">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Automation Rules</h3>
                            <button
                                type="button"
                                onClick={() => {
                                    setShowAddRecurring(true);
                                    setEditingRecurringId(null);
                                    setNewRecurring({
                                        name: '', amount: '', type: 'Expense', from_account_id: '',
                                        currency: currentCurrency,
                                        to_account_id: '', frequency: 'Monthly', day_of_month: '1', month_of_year: '1',
                                        start_period: '', end_period: '', auto_post: true,
                                    });
                                }}
                                className="p-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded"
                                aria-label="Add recurring rule"
                                title="Add recurring rule"
                            >
                                <Plus size={14} />
                            </button>
                        </div>
                        <div className="space-y-2">
                            {recurringItems.map((item) => (
                                <div key={item.id} className="flex items-center justify-between py-2 px-3 bg-slate-800/30 border border-slate-700">
                                    <div>
                                        <p className="text-xs font-medium">{item.name}</p>
                                        <p className="text-[10px] text-slate-500">
                                            {item.frequency} / {formatCurrencyWithSetting(item.amount, item.currency || currentCurrency)}
                                            {(item.start_period || item.end_period) && ` / ${item.start_period || '...'}-${item.end_period || '...'}`}
                                            {!item.auto_post && ' / no auto-post'}
                                        </p>
                                    </div>
                                    <div className="flex gap-1">
                                        <button
                                            type="button"
                                            onClick={() => handleEditRecurring(item)}
                                            className="p-1 text-slate-500 hover:text-cyan-400"
                                            aria-label="Edit recurring rule"
                                            title="Edit recurring rule"
                                        >
                                            <Edit size={12} />
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => handleDeleteRecurring(item.id)}
                                            className="p-1 text-slate-500 hover:text-rose-400"
                                            aria-label="Delete recurring rule"
                                            title="Delete recurring rule"
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                        {showAddRecurring && (
                            <div className="border border-cyan-800/50 bg-cyan-900/10 p-4 space-y-4 animate-in fade-in slide-in-from-top-2">
                                <div className="flex justify-between items-center border-b border-cyan-800/30 pb-2">
                                    <span className="text-[10px] font-bold text-cyan-500 uppercase">{editingRecurringId ? 'Edit Recurring Rule' : 'New Recurring Rule'}</span>
                                    <button
                                        type="button"
                                        onClick={() => setShowAddRecurring(false)}
                                        className="text-slate-500 hover:text-white"
                                        aria-label="Close recurring modal"
                                        title="Close recurring modal"
                                    >
                                        <X size={14} />
                                    </button>
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div className="col-span-2">
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Rule Name</label>
                                        <input
                                            type="text"
                                            placeholder="e.g., Rent, Netflix"
                                            value={newRecurring.name}
                                            onChange={e => setNewRecurring({ ...newRecurring, name: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                                        <div className="relative">
                                            <span className="absolute left-2 top-1.5 text-slate-500 text-xs">{getCurrencySymbol(newRecurring.currency)}</span>
                                            <input
                                                type="number"
                                                value={newRecurring.amount}
                                                onChange={e => setNewRecurring({ ...newRecurring, amount: e.target.value })}
                                                className="w-full bg-slate-900 border border-slate-700 pl-6 pr-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                            />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Currency</label>
                                        <select
                                            value={newRecurring.currency}
                                            onChange={e => setNewRecurring({ ...newRecurring, currency: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            {CURRENCIES.map((currency) => (
                                                <option key={currency} value={currency}>{currency}</option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Type</label>
                                        <select
                                            value={newRecurring.type}
                                            onChange={e => {
                                                const nextType = e.target.value as TransactionKind;
                                                setNewRecurring({ ...newRecurring, type: nextType, from_account_id: '', to_account_id: '' });
                                            }}
                                            title={typeDescription(newRecurring.type)}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            {TRANSACTION_TYPES.map((option) => (
                                                <option key={option.value} value={option.value} title={option.description}>
                                                    {option.label}
                                                </option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                                        <select
                                            value={newRecurring.from_account_id}
                                            onChange={e => setNewRecurring({ ...newRecurring, from_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {recurringFromAccounts.map(a => (
                                                <option key={a.id} value={a.id}>{a.name}</option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To Account</label>
                                        <select
                                            value={newRecurring.to_account_id}
                                            onChange={e => setNewRecurring({ ...newRecurring, to_account_id: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="">Select...</option>
                                            {recurringToAccounts.map(a => (
                                                <option key={a.id} value={a.id}>{a.name}</option>
                                            ))}
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Frequency</label>
                                        <select
                                            value={newRecurring.frequency}
                                            onChange={e => setNewRecurring({ ...newRecurring, frequency: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                        >
                                            <option value="Monthly">Monthly</option>
                                            <option value="Yearly">Yearly</option>
                                        </select>
                                    </div>

                                    {newRecurring.frequency === 'Monthly' ? (
                                        <div>
                                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Day of Month</label>
                                            <input
                                                type="number"
                                                min="1"
                                                max="31"
                                                value={newRecurring.day_of_month}
                                                onChange={e => setNewRecurring({ ...newRecurring, day_of_month: e.target.value })}
                                                className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                            />
                                        </div>
                                    ) : (
                                        <>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Month</label>
                                                <select
                                                    value={newRecurring.month_of_year}
                                                    onChange={e => setNewRecurring({ ...newRecurring, month_of_year: e.target.value })}
                                                    className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs focus:border-cyan-500 focus:outline-none"
                                                >
                                                    <option value="1">January</option>
                                                    <option value="2">February</option>
                                                    <option value="3">March</option>
                                                    <option value="4">April</option>
                                                    <option value="5">May</option>
                                                    <option value="6">June</option>
                                                    <option value="7">July</option>
                                                    <option value="8">August</option>
                                                    <option value="9">September</option>
                                                    <option value="10">October</option>
                                                    <option value="11">November</option>
                                                    <option value="12">December</option>
                                                </select>
                                            </div>
                                            <div>
                                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Day</label>
                                                <input
                                                    type="number"
                                                    min="1"
                                                    max="31"
                                                    value={newRecurring.day_of_month}
                                                    onChange={e => setNewRecurring({ ...newRecurring, day_of_month: e.target.value })}
                                                    className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                                />
                                            </div>
                                        </>
                                    )}

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Start Month</label>
                                        <input
                                            type="month"
                                            value={newRecurring.start_period}
                                            onChange={e => setNewRecurring({ ...newRecurring, start_period: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">End Month</label>
                                        <input
                                            type="month"
                                            value={newRecurring.end_period}
                                            onChange={e => setNewRecurring({ ...newRecurring, end_period: e.target.value })}
                                            className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:border-cyan-500 focus:outline-none"
                                        />
                                    </div>

                                    <label className="col-span-2 flex items-center gap-2 text-xs text-slate-300">
                                        <input
                                            type="checkbox"
                                            checked={newRecurring.auto_post}
                                            onChange={e => setNewRecurring({ ...newRecurring, auto_post: e.target.checked })}
                                            className="accent-cyan-500"
                                        />
                                        Auto post journal entries
                                    </label>
                                </div>

                                <div className="flex gap-2 pt-2">
                                    <button onClick={handleAddRecurring} className="flex-1 bg-cyan-600 hover:bg-cyan-500 py-2 text-xs font-bold text-white uppercase tracking-wider">
                                        {editingRecurringId ? 'Update Rule' : 'Create Rule'}
                                    </button>
                                    <button onClick={() => setShowAddRecurring(false)} className="px-4 bg-slate-800 hover:bg-slate-700 py-2 text-xs font-bold text-slate-400 uppercase">Cancel</button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </TabPanel>
    );

    const rightPane = (
        <div className="space-y-3 h-full flex flex-col">
            <div className="border border-slate-800 bg-slate-900/70 p-3 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="grid grid-cols-2 xl:grid-cols-4 gap-x-4 gap-y-1 text-[10px] text-slate-400 flex-1">
                        <span>{transactionTotal} results</span>
                        <span className="font-mono-nums text-emerald-400">Income {formatCurrency(loadedIncome)}</span>
                        <span className="font-mono-nums text-rose-400">Outflow {formatCurrency(loadedOutflow)}</span>
                        <span className={`font-mono-nums ${loadedNet >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            Net {formatCurrency(loadedNet)} / Avg {formatCurrency(loadedAverage)}
                        </span>
                    </div>
                    <button
                        type="button"
                        onClick={() => setShowFilters((value) => !value)}
                        className={`p-1.5 border text-slate-300 hover:text-emerald-300 ${showFilters ? 'border-emerald-700 bg-emerald-950/30' : 'border-slate-700 bg-slate-800 hover:bg-slate-700'}`}
                        aria-label="Toggle transaction filters"
                        title="Transaction filters"
                    >
                        <SlidersHorizontal size={14} />
                    </button>
                </div>
                {showFilters && (
                    <>
                        <div className="grid grid-cols-2 xl:grid-cols-4 gap-2">
                    <input
                        type="date"
                        value={filters.startDate}
                        onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                        title="Start date"
                    />
                    <input
                        type="date"
                        value={filters.endDate}
                        onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                        title="End date"
                    />
                    <select
                        value={filters.type}
                        onChange={(e) => setFilters({ ...filters, type: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                        title="Transaction type"
                    >
                        <option value="">All types</option>
                        {TRANSACTION_TYPES.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                    <select
                        value={filters.accountId}
                        onChange={(e) => setFilters({ ...filters, accountId: e.target.value })}
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                        title="Account"
                    >
                        <option value="">All accounts</option>
                        {accounts.map((account) => (
                            <option key={account.id} value={account.id}>{account.name}</option>
                        ))}
                    </select>
                    <input
                        type="text"
                        value={filters.q}
                        onChange={(e) => setFilters({ ...filters, q: e.target.value })}
                        placeholder="Description"
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                    />
                    <input
                        type="text"
                        value={filters.category}
                        onChange={(e) => setFilters({ ...filters, category: e.target.value })}
                        placeholder="Category"
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                    />
                    <input
                        type="number"
                        value={filters.amountMin}
                        onChange={(e) => setFilters({ ...filters, amountMin: e.target.value })}
                        placeholder="Min amount"
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                    />
                    <input
                        type="number"
                        value={filters.amountMax}
                        onChange={(e) => setFilters({ ...filters, amountMax: e.target.value })}
                        placeholder="Max amount"
                        className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                    />
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap gap-1">
                        <button onClick={() => setPresetRange('today')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-[10px]">Today</button>
                        <button onClick={() => setPresetRange('week')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-[10px]">This week</button>
                        <button onClick={() => setPresetRange('month')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-[10px]">This month</button>
                        <button onClick={() => setPresetRange('30d')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-[10px]">Last 30 days</button>
                    </div>
                    <div className="flex gap-2">
                        <button onClick={() => applyFilters()} className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-[10px] font-bold">Apply</button>
                        <button onClick={clearFilters} className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-bold">Clear</button>
                    </div>
                        </div>
                    </>
                )}
            </div>
            <div className="flex-1 overflow-auto space-y-0.5">
                {transactions.length === 0 ? (
                    <p className="text-slate-600 text-xs py-8 text-center">No transactions yet</p>
                ) : (
                    transactions.map((tx) => (
                        <div key={tx.id} className="flex items-center justify-between py-2 px-2 hover:bg-slate-800/50 transition-colors group">
                            <div className="flex items-center gap-2">
                                {tx.type === 'Income' ? <ArrowUpCircle className="text-emerald-500" size={14} /> : tx.type === 'Expense' || tx.type === 'LiabilityPayment' ? <ArrowDownCircle className="text-rose-500" size={14} /> : <RefreshCw className="text-cyan-500" size={14} />}
                                <div>
                                    <p className="text-xs">{tx.description}</p>
                                    <p className="text-[10px] text-slate-600">{tx.date} • {tx.category || 'Other'}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={`text-xs font-mono-nums ${tx.type === 'Income' ? 'text-emerald-500' : tx.type === 'Expense' || tx.type === 'LiabilityPayment' ? 'text-rose-500' : 'text-cyan-500'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' || tx.type === 'LiabilityPayment' ? '-' : ''}{formatCurrencyWithSetting(tx.amount, tx.currency || currentCurrency)}
                                </span>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100">
                                    <button
                                        type="button"
                                        className="p-1 hover:text-slate-300"
                                        onClick={() => handleEditTransaction(tx)}
                                        aria-label="Edit transaction"
                                        title="Edit transaction"
                                    >
                                        <Edit size={12} />
                                    </button>
                                    <button
                                        type="button"
                                        className="p-1 hover:text-rose-400"
                                        onClick={() => handleDeleteTransaction(tx.id)}
                                        aria-label="Delete transaction"
                                        title="Delete transaction"
                                    >
                                        <Trash2 size={12} />
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))
                )}
                {transactions.length < transactionTotal && (
                    <button
                        type="button"
                        onClick={() => fetchTransactionsOnly(filters, true)}
                        className="w-full py-2 text-xs text-cyan-400 hover:bg-slate-800/50"
                    >
                        Load more ({transactions.length}/{transactionTotal})
                    </button>
                )}
            </div>
        </div>
    );

    return (
        <div className="h-full flex flex-col p-2 overflow-hidden">
            <SplitView
                left={leftPane}
                right={rightPane}
            />
        </div>
    );
}
