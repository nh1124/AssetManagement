import { useEffect, useMemo, useState } from 'react';
import { Cpu, Edit, Package, Plus, RefreshCw, Save, SlidersHorizontal, Trash2, Wallet, X } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import {
    autoUpdateExchangeRates,
    createAccount,
    createExchangeRate,
    createProductReservePools,
    createProduct,
    createRegistryEntry,
    deleteAccount,
    deleteExchangeRate,
    deleteProduct,
    deleteRegistryEntry,
    getAccounts,
    getAccountTree,
    getCapsules,
    getExchangeRates,
    getProducts,
    getRegistryEntries,
    seedDefaultAccounts,
    updateAccount,
    updateProduct,
    updateRegistryEntry,
} from '../api';
import { useToast } from '../components/Toast';
import { useClient } from '../context/ClientContext';
import { formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import type { Account, AccountRole, AccountTreeNode, Capsule, ExchangeRate, LiabilityPaymentPolicy, Product, RegistryEntry } from '../types';

const TABS = [
    { id: 'accounts', label: 'Accounts' },
    { id: 'exchange-rates', label: 'Exchange Rates' },
    { id: 'sources', label: 'Sources' },
];

const SOURCES_INNER_TABS = [
    { id: 'service', label: 'Service' },
    { id: 'income', label: 'Income' },
    { id: 'debt', label: 'Debt' },
    { id: 'allocation', label: 'Allocation' },
    { id: 'assets', label: 'Assets' },
    { id: 'items', label: 'Items' },
];

const TAB_DEFAULTS: Record<string, Partial<{
    entry_type: string; transaction_type: string; line_type: string;
    generate_recurring: boolean; budget_active: boolean;
}>> = {
    service:    { entry_type: 'service',    transaction_type: 'Expense',          line_type: 'expense',      generate_recurring: true,  budget_active: true  },
    income:     { entry_type: 'income',     transaction_type: 'Income',           line_type: 'income',       generate_recurring: true,  budget_active: true  },
    debt:       { entry_type: 'debt',       transaction_type: 'LiabilityPayment', line_type: 'debt_payment', generate_recurring: true,  budget_active: true  },
    allocation: { entry_type: 'allocation', transaction_type: 'Transfer',         line_type: 'allocation',   generate_recurring: false, budget_active: false },
};

const ACCOUNT_TYPES = [
    { value: 'asset', label: 'Asset', color: 'text-emerald-400' },
    { value: 'liability', label: 'Liability', color: 'text-rose-400' },
    { value: 'income', label: 'Income', color: 'text-cyan-400' },
    { value: 'expense', label: 'Expense', color: 'text-amber-400' },
];

const ACCOUNT_ROLES: Array<{ value: AccountRole; label: string }> = [
    { value: 'defense', label: 'Defense' },
    { value: 'growth', label: 'Growth' },
    { value: 'earmarked', label: 'Earmarked' },
    { value: 'operating', label: 'Operating' },
    { value: 'unassigned', label: 'Unassigned' },
];

const LIABILITY_POLICIES: Array<{ value: LiabilityPaymentPolicy; label: string }> = [
    { value: 'full', label: 'Full' },
    { value: 'minimum', label: 'Minimum' },
    { value: 'fixed', label: 'Fixed' },
    { value: 'installment', label: 'Installment' },
    { value: 'revolving', label: 'Revolving' },
];

const emptyAccountDraft = () => ({
    name: '',
    account_type: 'expense',
    role: 'unassigned' as AccountRole,
    role_target_amount: '',
    parent_id: '',
    liability_closing_day: '',
    liability_payment_day: '',
    liability_payment_month_offset: '0',
    liability_payment_policy: 'full' as LiabilityPaymentPolicy,
    liability_minimum_payment: '',
    liability_fixed_payment_amount: '',
    liability_installment_months: '',
    liability_revolving_rate: '',
});

const nullableNumber = (value: string | number | null | undefined) => (
    value === '' || value === null || value === undefined ? null : Number(value)
);

const EMPTY_PRODUCT_FORM = {
    name: '',
    category: 'Uncategorized',
    location: '',
    is_asset: true,
    purchase_price: '',
    purchase_date: '',
    lifespan_months: '',
    budget_account_id: '',
    funding_capsule_id: '',
    budget_treatment: 'auto',
    last_unit_price: '',
    units_per_purchase: '1',
    frequency_days: '',
    last_purchase_date: '',
};

const EMPTY_REGISTRY_FORM = {
    name: '',
    entry_type: 'service',
    category: '',
    amount: '',
    currency: 'JPY',
    frequency: 'Monthly',
    frequency_days: '',
    day_of_month: '1',
    month_of_year: '1',
    transaction_type: 'Expense',
    line_type: 'expense',
    budget_account_id: '',
    source_account_id: '',
    destination_account_id: '',
    budget_treatment: 'expense_only',
    generate_recurring: true,
    budget_active: true,
    is_active: true,
    start_period: '',
    end_period: '',
    note: '',
};

type ProductForm = typeof EMPTY_PRODUCT_FORM;
type ProductKind = 'asset' | 'item';

const PRODUCT_FILTER_STORAGE_KEY = 'finance_registry_product_filters';

const defaultProductFilters = {
    q: '',
    category: '',
    budgetAccountId: '',
    fundingCapsuleId: '',
    location: '',
    treatment: '',
    dateFrom: '',
    dateTo: '',
    amountMin: '',
    amountMax: '',
};

type ProductFilters = typeof defaultProductFilters;

const emptyProductFilterSet = (): Record<ProductKind, ProductFilters> => ({
    asset: { ...defaultProductFilters },
    item: { ...defaultProductFilters },
});

const loadStoredProductFilters = (): Record<ProductKind, ProductFilters> => {
    try {
        const parsed = JSON.parse(localStorage.getItem(PRODUCT_FILTER_STORAGE_KEY) || '{}');
        return {
            asset: { ...defaultProductFilters, ...(parsed.asset ?? {}) },
            item: { ...defaultProductFilters, ...(parsed.item ?? {}) },
        };
    } catch {
        return emptyProductFilterSet();
    }
};

const productPrice = (product: Product) => product.purchase_price ?? product.last_unit_price ?? 0;
const productMonthlyValue = (product: Product, kind: ProductKind) => {
    const price = productPrice(product);
    return kind === 'asset'
        ? product.lifespan_months ? price / product.lifespan_months : 0
        : product.monthly_cost ?? 0;
};
const productCategoryLabel = (product: Product) => product.budget_account_name || product.category || 'Uncategorized';
const productDate = (product: Product, kind: ProductKind) => (
    kind === 'asset'
        ? product.purchase_date || product.last_purchase_date || ''
        : product.next_purchase_date || product.last_purchase_date || ''
);
const productTreatment = (product: Product) => product.effective_budget_treatment || product.budget_treatment || 'auto';

const matchesProductFilters = (product: Product, filters: ProductFilters, kind: ProductKind) => {
    const query = filters.q.trim().toLowerCase();
    if (query) {
        const haystack = [
            product.name,
            product.category,
            product.budget_account_name,
            product.funding_capsule_name,
            product.location,
        ].filter(Boolean).join(' ').toLowerCase();
        if (!haystack.includes(query)) return false;
    }

    if (filters.category && productCategoryLabel(product) !== filters.category) return false;
    if (filters.budgetAccountId && String(product.budget_account_id ?? '') !== filters.budgetAccountId) return false;
    if (filters.fundingCapsuleId && String(product.funding_capsule_id ?? '') !== filters.fundingCapsuleId) return false;
    if (filters.location && (product.location || '') !== filters.location) return false;
    if (filters.treatment && productTreatment(product) !== filters.treatment) return false;

    const date = productDate(product, kind);
    if (filters.dateFrom && (!date || date < filters.dateFrom)) return false;
    if (filters.dateTo && (!date || date > filters.dateTo)) return false;

    const amount = productPrice(product);
    if (filters.amountMin && amount < Number(filters.amountMin)) return false;
    if (filters.amountMax && amount > Number(filters.amountMax)) return false;

    return true;
};

const summarizeProducts = (rows: Product[], kind: ProductKind) => {
    const categories = new Map<string, { count: number; value: number; monthly: number }>();
    let totalValue = 0;
    let monthlyTotal = 0;

    rows.forEach((product) => {
        const value = productPrice(product);
        const monthly = productMonthlyValue(product, kind);
        const category = productCategoryLabel(product);
        const current = categories.get(category) ?? { count: 0, value: 0, monthly: 0 };
        current.count += 1;
        current.value += value;
        current.monthly += monthly;
        categories.set(category, current);
        totalValue += value;
        monthlyTotal += monthly;
    });

    return {
        totalValue,
        monthlyTotal,
        categoryBreakdown: Array.from(categories.entries())
            .map(([category, values]) => ({ category, ...values }))
            .sort((a, b) => b.value - a.value),
    };
};

function productToForm(product: Product): ProductForm {
    return {
        name: product.name ?? '',
        category: product.category ?? 'Uncategorized',
        location: product.location ?? '',
        is_asset: product.is_asset ?? true,
        purchase_price: product.purchase_price != null ? String(product.purchase_price) : '',
        purchase_date: product.purchase_date ?? '',
        lifespan_months: product.lifespan_months != null ? String(product.lifespan_months) : '',
        budget_account_id: product.budget_account_id != null ? String(product.budget_account_id) : '',
        funding_capsule_id: product.funding_capsule_id != null ? String(product.funding_capsule_id) : '',
        budget_treatment: product.budget_treatment ?? 'auto',
        last_unit_price: product.last_unit_price != null ? String(product.last_unit_price) : '',
        units_per_purchase: product.units_per_purchase != null ? String(product.units_per_purchase) : '1',
        frequency_days: product.frequency_days != null ? String(product.frequency_days) : '',
        last_purchase_date: product.last_purchase_date ?? '',
    };
}

function toProductPayload(form: ProductForm) {
    const purchasePrice = form.purchase_price ? parseFloat(form.purchase_price) : null;
    const lastUnitPrice = form.last_unit_price
        ? parseFloat(form.last_unit_price)
        : purchasePrice ?? 0;

    return {
        name: form.name.trim(),
        category: form.category.trim() || 'Uncategorized',
        location: form.location.trim() || null,
        last_unit_price: lastUnitPrice,
        units_per_purchase: form.units_per_purchase ? parseInt(form.units_per_purchase, 10) : 1,
        frequency_days: form.frequency_days ? parseInt(form.frequency_days, 10) : 0,
        last_purchase_date: form.last_purchase_date || null,
        is_asset: form.is_asset,
        lifespan_months: form.lifespan_months ? parseInt(form.lifespan_months, 10) : null,
        budget_account_id: form.budget_account_id ? parseInt(form.budget_account_id, 10) : null,
        funding_capsule_id: form.funding_capsule_id ? parseInt(form.funding_capsule_id, 10) : null,
        budget_treatment: form.budget_treatment,
        purchase_price: purchasePrice,
        purchase_date: form.purchase_date || null,
    };
}

interface ProductModalProps {
    initialType: 'asset' | 'item';
    product: Product | null;
    budgetAccounts: Account[];
    fundingCapsules: Capsule[];
    onClose: () => void;
    onSaved: () => void;
}

function ProductModal({ initialType, product, budgetAccounts, fundingCapsules, onClose, onSaved }: ProductModalProps) {
    const [form, setForm] = useState<ProductForm>(() => {
        if (product) return productToForm(product);
        return { ...EMPTY_PRODUCT_FORM, is_asset: initialType === 'asset' };
    });
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [error, setError] = useState('');

    const set = (key: keyof ProductForm, value: string | boolean) => {
        setForm((prev) => ({ ...prev, [key]: value }));
    };

    const inputClass = 'w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500';

    const handleSave = async () => {
        if (!form.name.trim()) {
            setError('Name is required.');
            return;
        }

        setSaving(true);
        setError('');
        try {
            const payload = toProductPayload(form);
            if (product) {
                await updateProduct(product.id, payload);
            } else {
                await createProduct(payload);
            }
            onSaved();
            onClose();
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Failed to save product.');
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!product || !window.confirm(`Delete "${product.name}"?`)) return;
        setDeleting(true);
        setError('');
        try {
            await deleteProduct(product.id);
            onSaved();
            onClose();
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Failed to delete product.');
        } finally {
            setDeleting(false);
        }
    };

    const field = (label: string, node: React.ReactNode) => (
        <div>
            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</label>
            {node}
        </div>
    );

    return (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
            <div className="w-full max-w-2xl max-h-[90vh] overflow-auto bg-slate-950 border border-slate-700">
                <div className="flex items-center justify-between p-4 border-b border-slate-800">
                    <h2 className="text-sm font-semibold">{product ? 'Edit Product' : 'Add Product'}</h2>
                    <button onClick={onClose} className="p-1 text-slate-500 hover:text-slate-200">
                        <X size={16} />
                    </button>
                </div>

                <div className="p-4 space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div className="md:col-span-2">
                            {field(
                                'Name',
                                <input
                                    autoFocus
                                    className={inputClass}
                                    value={form.name}
                                    onChange={(event) => set('name', event.target.value)}
                                    placeholder="Laptop, coffee beans, shampoo..."
                                />
                            )}
                        </div>
                        {field(
                            'Type',
                            <select
                                className={inputClass}
                                value={form.is_asset ? 'asset' : 'item'}
                                onChange={(event) => set('is_asset', event.target.value === 'asset')}
                            >
                                <option value="asset">Fixed Asset</option>
                                <option value="item">Consumable</option>
                            </select>
                        )}
                        {field(
                            'Budget Category',
                            <select
                                className={inputClass}
                                value={form.budget_account_id}
                                onChange={(event) => set('budget_account_id', event.target.value)}
                            >
                                <option value="">Not linked</option>
                                {budgetAccounts.map((account) => (
                                    <option key={account.id} value={account.id}>{account.name}</option>
                                ))}
                            </select>
                        )}
                        {field(
                            'Budget Treatment',
                            <select
                                className={inputClass}
                                value={form.budget_treatment}
                                onChange={(event) => set('budget_treatment', event.target.value)}
                            >
                                <option value="auto">Auto</option>
                                <option value="expense_only">Expense only</option>
                                <option value="reserve_allocation">Reserve allocation</option>
                                <option value="asset_replacement">Asset replacement</option>
                            </select>
                        )}
                        {field(
                            'Funding Capsule',
                            <select
                                className={inputClass}
                                value={form.funding_capsule_id}
                                onChange={(event) => set('funding_capsule_id', event.target.value)}
                                disabled={form.budget_treatment === 'expense_only'}
                            >
                                <option value="">{form.budget_treatment === 'expense_only' ? 'Not used for expense only' : 'Not linked'}</option>
                                {fundingCapsules.map((capsule) => (
                                    <option key={capsule.id} value={capsule.id}>{capsule.name}</option>
                                ))}
                            </select>
                        )}
                        {field(
                            'Location / Store',
                            <input
                                className={inputClass}
                                value={form.location}
                                onChange={(event) => set('location', event.target.value)}
                                placeholder="Home office, Amazon..."
                            />
                        )}
                        {field(
                            'Reference Price',
                            <input
                                className={inputClass}
                                type="number"
                                min="0"
                                value={form.last_unit_price}
                                onChange={(event) => set('last_unit_price', event.target.value)}
                                placeholder="0"
                            />
                        )}
                    </div>

                    {form.is_asset ? (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 border border-slate-800 p-3">
                            <p className="md:col-span-3 text-[10px] text-slate-500 uppercase tracking-wider">Asset Lifecycle</p>
                            {field(
                                'Purchase Price',
                                <input
                                    className={inputClass}
                                    type="number"
                                    min="0"
                                    value={form.purchase_price}
                                    onChange={(event) => set('purchase_price', event.target.value)}
                                    placeholder="120000"
                                />
                            )}
                            {field(
                                'Purchase Date',
                                <input
                                    className={inputClass}
                                    type="date"
                                    value={form.purchase_date}
                                    onChange={(event) => set('purchase_date', event.target.value)}
                                />
                            )}
                            {field(
                                'Lifespan Months',
                                <input
                                    className={inputClass}
                                    type="number"
                                    min="0"
                                    value={form.lifespan_months}
                                    onChange={(event) => set('lifespan_months', event.target.value)}
                                    placeholder="36"
                                />
                            )}
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 border border-slate-800 p-3">
                            <p className="md:col-span-3 text-[10px] text-slate-500 uppercase tracking-wider">Unit Economics</p>
                            {field(
                                'Units Per Purchase',
                                <input
                                    className={inputClass}
                                    type="number"
                                    min="1"
                                    value={form.units_per_purchase}
                                    onChange={(event) => set('units_per_purchase', event.target.value)}
                                    placeholder="1"
                                />
                            )}
                            {field(
                                'Frequency Days',
                                <input
                                    className={inputClass}
                                    type="number"
                                    min="0"
                                    value={form.frequency_days}
                                    onChange={(event) => set('frequency_days', event.target.value)}
                                    placeholder="30"
                                />
                            )}
                            {field(
                                'Last Purchase Date',
                                <input
                                    className={inputClass}
                                    type="date"
                                    value={form.last_purchase_date}
                                    onChange={(event) => set('last_purchase_date', event.target.value)}
                                />
                            )}
                        </div>
                    )}

                    {error && <p className="text-xs text-rose-400">{error}</p>}
                </div>

                <div className="p-4 border-t border-slate-800 flex items-center justify-between">
                    <div>
                        {product && (
                            <button
                                onClick={handleDelete}
                                disabled={deleting}
                                className="px-3 py-1.5 border border-rose-900 text-rose-400 hover:bg-rose-950/30 text-xs flex items-center gap-1 disabled:opacity-50"
                            >
                                <Trash2 size={12} />
                                {deleting ? 'Deleting...' : 'Delete'}
                            </button>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button onClick={onClose} className="px-3 py-1.5 border border-slate-700 text-slate-400 hover:bg-slate-800 text-xs">
                            Cancel
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold disabled:opacity-50"
                        >
                            {saving ? 'Saving...' : 'Save'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default function Registry() {
    const [activeTab, setActiveTab] = useState('accounts');
    const [products, setProducts] = useState<Product[]>([]);
    const [registryEntries, setRegistryEntries] = useState<RegistryEntry[]>([]);
    const [capsules, setCapsules] = useState<Capsule[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [accountTree, setAccountTree] = useState<Record<string, AccountTreeNode[]>>({});
    const [exchangeRates, setExchangeRates] = useState<ExchangeRate[]>([]);
    const [autoUpdatingRates, setAutoUpdatingRates] = useState(false);
    const [lastRateUpdate, setLastRateUpdate] = useState<{
        updated: number;
        skipped: number;
        errors: number;
    } | null>(null);
    const [rateDraft, setRateDraft] = useState({
        base_currency: 'USD',
        quote_currency: 'JPY',
        rate: '',
        as_of_date: new Date().toISOString().slice(0, 10),
        source: 'manual',
    });
    const [isSavingRate, setIsSavingRate] = useState(false);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editForm, setEditForm] = useState<any>({});
    const [newAccount, setNewAccount] = useState(emptyAccountDraft());
    const [showAddAccount, setShowAddAccount] = useState(false);
    const [productModal, setProductModal] = useState<{ type: 'asset' | 'item'; product: Product | null } | null>(null);
    const [loadingProducts, setLoadingProducts] = useState(false);
    const [productFilters, setProductFilters] = useState<Record<ProductKind, ProductFilters>>(() => loadStoredProductFilters());
    const [productFilterDrafts, setProductFilterDrafts] = useState<Record<ProductKind, ProductFilters>>(() => loadStoredProductFilters());
    const [showProductFilters, setShowProductFilters] = useState<Record<ProductKind, boolean>>({ asset: false, item: false });
    const [showRegistryForm, setShowRegistryForm] = useState(false);
    const [editingRegistryId, setEditingRegistryId] = useState<number | null>(null);
    const [registryForm, setRegistryForm] = useState({ ...EMPTY_REGISTRY_FORM });
    const [sourcesTab, setSourcesTab] = useState('service');
    const [showSourcesFilter, setShowSourcesFilter] = useState(false);
    const [sourcesFilterDraft, setSourcesFilterDraft] = useState({ q: '', budgetAccountId: '' });
    const [sourcesFilter, setSourcesFilter] = useState({ q: '', budgetAccountId: '' });
    const { showToast } = useToast();
    const { currentClient } = useClient();

    const assets = useMemo(() => products.filter((product) => product.is_asset), [products]);
    const items = useMemo(() => products.filter((product) => !product.is_asset), [products]);

    useEffect(() => {
        fetchData();
    }, []);

    useEffect(() => {
        const currency = currentClient?.general_settings?.currency;
        if (currency) {
            setRateDraft((prev) => ({ ...prev, quote_currency: currency }));
        }
    }, [currentClient?.general_settings?.currency]);

    useEffect(() => {
        if (activeTab === 'exchange-rates') {
            handleAutoUpdateRates(true);
        }
    }, [activeTab]);

    const fetchData = async () => {
        try {
            setLoadingProducts(true);
            const [productsData, accountsData, treeData, ratesData, capsulesData, registryData] = await Promise.all([
                getProducts(),
                getAccounts(),
                getAccountTree(),
                getExchangeRates(),
                getCapsules(),
                getRegistryEntries(),
            ]);
            setProducts(productsData);
            setAccounts(accountsData);
            setAccountTree(treeData);
            setExchangeRates(ratesData);
            setCapsules(capsulesData);
            setRegistryEntries(registryData);
        } catch (error) {
            console.error('Failed to fetch registry data:', error);
            try {
                await seedDefaultAccounts();
                const [accountsData, treeData] = await Promise.all([getAccounts(), getAccountTree()]);
                setAccounts(accountsData);
                setAccountTree(treeData);
            } catch {
                showToast('Failed to load registry data', 'error');
            }
        } finally {
            setLoadingProducts(false);
        }
    };

    const formatCurrency = (value: number | null | undefined) =>
        formatCurrencyWithSetting(value, currentClient?.general_settings?.currency);

    const registryPayload = () => ({
        name: registryForm.name.trim(),
        entry_type: registryForm.entry_type,
        category: registryForm.category.trim() || null,
        amount: Number(registryForm.amount || 0),
        currency: registryForm.currency || currentClient?.general_settings?.currency || 'JPY',
        frequency: registryForm.frequency,
        frequency_days: registryForm.frequency === 'EveryNDays' && registryForm.frequency_days ? Number(registryForm.frequency_days) : null,
        day_of_month: Number(registryForm.day_of_month || 1),
        month_of_year: registryForm.frequency === 'Yearly' ? Number(registryForm.month_of_year || 1) : null,
        transaction_type: registryForm.transaction_type,
        line_type: registryForm.line_type,
        budget_account_id: registryForm.budget_account_id ? Number(registryForm.budget_account_id) : null,
        source_account_id: registryForm.source_account_id ? Number(registryForm.source_account_id) : null,
        destination_account_id: registryForm.destination_account_id ? Number(registryForm.destination_account_id) : null,
        budget_treatment: registryForm.budget_treatment,
        generate_recurring: registryForm.generate_recurring,
        budget_active: registryForm.budget_active,
        is_active: registryForm.is_active,
        start_period: registryForm.start_period || null,
        end_period: registryForm.end_period || null,
        note: registryForm.note.trim() || null,
    });

    const resetRegistryForm = () => {
        setEditingRegistryId(null);
        setRegistryForm({ ...EMPTY_REGISTRY_FORM, currency: currentClient?.general_settings?.currency || 'JPY' });
        setShowRegistryForm(false);
    };

    const editRegistryEntry = (entry: RegistryEntry) => {
        setEditingRegistryId(entry.id);
        setRegistryForm({
            name: entry.name,
            entry_type: entry.entry_type,
            category: entry.category || '',
            amount: String(entry.amount ?? 0),
            currency: entry.currency || currentClient?.general_settings?.currency || 'JPY',
            frequency: entry.frequency,
            frequency_days: entry.frequency_days != null ? String(entry.frequency_days) : '',
            day_of_month: String(entry.day_of_month ?? 1),
            month_of_year: String(entry.month_of_year ?? 1),
            transaction_type: entry.transaction_type,
            line_type: entry.line_type,
            budget_account_id: entry.budget_account_id ? String(entry.budget_account_id) : '',
            source_account_id: entry.source_account_id ? String(entry.source_account_id) : '',
            destination_account_id: entry.destination_account_id ? String(entry.destination_account_id) : '',
            budget_treatment: entry.budget_treatment || 'expense_only',
            generate_recurring: entry.generate_recurring,
            budget_active: entry.budget_active,
            is_active: entry.is_active,
            start_period: entry.start_period || '',
            end_period: entry.end_period || '',
            note: entry.note || '',
        });
        setShowRegistryForm(true);
        setActiveTab('sources');
        const typeToTab: Record<string, string> = { service: 'service', income: 'income', debt: 'debt', allocation: 'allocation', asset: 'assets', item: 'items' };
        setSourcesTab(typeToTab[entry.entry_type] ?? 'service');
    };

    const saveRegistryEntry = async () => {
        if (!registryForm.name.trim() || !Number(registryForm.amount || 0)) {
            showToast('Name and amount are required', 'warning');
            return;
        }
        try {
            const payload = registryPayload();
            if (editingRegistryId) {
                await updateRegistryEntry(editingRegistryId, payload as any);
                showToast('Registry source updated', 'success');
            } else {
                await createRegistryEntry(payload as any);
                showToast('Registry source created', 'success');
            }
            resetRegistryForm();
            await fetchData();
        } catch {
            showToast('Failed to save registry source', 'error');
        }
    };

    const removeRegistryEntry = async (entry: RegistryEntry) => {
        try {
            await deleteRegistryEntry(entry.id);
            showToast('Registry source deactivated', 'info');
            await fetchData();
        } catch {
            showToast('Failed to deactivate registry source', 'error');
        }
    };

    const handleAddAccount = async () => {
        if (!newAccount.name.trim()) return;
        try {
            await createAccount({
                name: newAccount.name.toLowerCase().replace(/\s+/g, '_'),
                account_type: newAccount.account_type,
                role: newAccount.account_type === 'asset' ? newAccount.role : 'unassigned',
                role_target_amount: newAccount.role_target_amount ? Number(newAccount.role_target_amount) : null,
                parent_id: newAccount.parent_id ? Number(newAccount.parent_id) : null,
                ...(newAccount.account_type === 'liability' ? {
                    liability_closing_day: nullableNumber(newAccount.liability_closing_day),
                    liability_payment_day: nullableNumber(newAccount.liability_payment_day),
                    liability_payment_month_offset: Number(newAccount.liability_payment_month_offset || 0),
                    liability_payment_policy: newAccount.liability_payment_policy,
                    liability_minimum_payment: nullableNumber(newAccount.liability_minimum_payment),
                    liability_fixed_payment_amount: nullableNumber(newAccount.liability_fixed_payment_amount),
                    liability_installment_months: nullableNumber(newAccount.liability_installment_months),
                    liability_revolving_rate: nullableNumber(newAccount.liability_revolving_rate),
                } : {}),
            });
            showToast(`Account "${newAccount.name}" created`, 'success');
            setNewAccount(emptyAccountDraft());
            setShowAddAccount(false);
            fetchData();
        } catch (error) {
            showToast('Failed to create account', 'error');
        }
    };

    const ensureProductReservePools = async () => {
        try {
            await createProductReservePools();
            showToast('Product reserve capsules are ready', 'success');
            await fetchData();
        } catch (error) {
            showToast('Failed to create reserve capsules', 'error');
        }
    };

    const setProductFilterDraft = (kind: ProductKind, key: keyof ProductFilters, value: string) => {
        setProductFilterDrafts((prev) => ({
            ...prev,
            [kind]: { ...prev[kind], [key]: value },
        }));
    };

    const applyProductFilters = (kind: ProductKind) => {
        const next = { ...productFilters, [kind]: { ...productFilterDrafts[kind] } };
        setProductFilters(next);
        localStorage.setItem(PRODUCT_FILTER_STORAGE_KEY, JSON.stringify(next));
    };

    const clearProductFilters = (kind: ProductKind) => {
        const cleared = { ...defaultProductFilters };
        const next = { ...productFilters, [kind]: cleared };
        setProductFilters(next);
        setProductFilterDrafts((prev) => ({ ...prev, [kind]: cleared }));
        localStorage.setItem(PRODUCT_FILTER_STORAGE_KEY, JSON.stringify(next));
    };

    const handleUpdateAccount = async (id: number) => {
        try {
            await updateAccount(id, editForm);
            showToast('Account updated', 'success');
            setEditingId(null);
            fetchData();
        } catch (error) {
            showToast('Failed to update account', 'error');
        }
    };

    const handleDeleteAccount = async (id: number) => {
        try {
            await deleteAccount(id);
            showToast('Account deactivated', 'info');
            fetchData();
        } catch (error) {
            showToast('Failed to delete account', 'error');
        }
    };

    const handleAddRate = async () => {
        const numericRate = Number(rateDraft.rate);
        if (!rateDraft.base_currency.trim() || !rateDraft.quote_currency.trim() || !numericRate) return;
        setIsSavingRate(true);
        try {
            await createExchangeRate({
                base_currency: rateDraft.base_currency.trim().toUpperCase(),
                quote_currency: rateDraft.quote_currency.trim().toUpperCase(),
                rate: numericRate,
                as_of_date: rateDraft.as_of_date,
                source: rateDraft.source || 'manual',
            });
            setRateDraft((prev) => ({ ...prev, rate: '' }));
            setExchangeRates(await getExchangeRates());
            showToast('Exchange rate saved', 'success');
        } catch (error: any) {
            showToast(error?.response?.data?.detail || 'Failed to save exchange rate', 'error');
        } finally {
            setIsSavingRate(false);
        }
    };

    const handleDeleteRate = async (id: number) => {
        try {
            await deleteExchangeRate(id);
            setExchangeRates((prev) => prev.filter((rate) => rate.id !== id));
            showToast('Exchange rate deleted', 'success');
        } catch (error: any) {
            showToast(error?.response?.data?.detail || 'Failed to delete exchange rate', 'error');
        }
    };

    const handleAutoUpdateRates = async (silent = false) => {
        setAutoUpdatingRates(true);
        try {
            const result = await autoUpdateExchangeRates();
            setLastRateUpdate({
                updated: result.updated.length,
                skipped: result.skipped.length,
                errors: result.errors.length,
            });
            setExchangeRates(await getExchangeRates());
            if (!silent) {
                const message = result.errors.length
                    ? `Updated ${result.updated.length}, ${result.errors.length} failed`
                    : `Updated ${result.updated.length}, skipped ${result.skipped.length}`;
                showToast(message, result.errors.length ? 'error' : 'success');
            }
        } catch (error: any) {
            if (!silent) {
                showToast(error?.response?.data?.detail || 'Failed to auto-update rates', 'error');
            }
        } finally {
            setAutoUpdatingRates(false);
        }
    };

    const renderProducts = (kind: ProductKind) => {
        const allRows = kind === 'asset' ? assets : items;
        const filters = productFilters[kind];
        const draft = productFilterDrafts[kind];
        const rows = allRows.filter((product) => matchesProductFilters(product, filters, kind));
        const summary = summarizeProducts(rows, kind);
        const activeFilterCount = Object.values(filters).filter(Boolean).length;
        const title = kind === 'asset' ? 'Fixed Assets' : 'Consumable Items';
        const categoryOptions = Array.from(new Set(allRows.map(productCategoryLabel))).sort();
        const budgetOptions = Array.from(
            new Map(
                allRows
                    .filter((product) => product.budget_account_id && product.budget_account_name)
                    .map((product) => [String(product.budget_account_id), product.budget_account_name as string])
            ).entries()
        ).sort((a, b) => a[1].localeCompare(b[1]));
        const fundingOptions = Array.from(
            new Map(
                allRows
                    .filter((product) => product.funding_capsule_id && product.funding_capsule_name)
                    .map((product) => [String(product.funding_capsule_id), product.funding_capsule_name as string])
            ).entries()
        ).sort((a, b) => a[1].localeCompare(b[1]));
        const locationOptions = Array.from(new Set(allRows.map((product) => product.location).filter(Boolean) as string[])).sort();
        const treatmentOptions = Array.from(new Set(allRows.map(productTreatment))).sort();

        return (
            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-sm font-semibold">{title}</h2>
                        <p className="text-[10px] text-slate-500">
                            {kind === 'asset'
                                ? 'Track durable purchases and monthly depreciation.'
                                : 'Track unit cost, replenishment timing, and monthly run-rate.'}
                        </p>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={ensureProductReservePools}
                            className="px-3 py-1.5 border border-purple-800 text-purple-200 hover:bg-purple-900/40 text-xs flex items-center gap-1"
                        >
                            <Wallet size={12} />
                            Reserve Pools
                        </button>
                        <button
                            onClick={() => setProductModal({ type: kind, product: null })}
                            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs flex items-center gap-1"
                        >
                            <Plus size={12} />
                            Add
                        </button>
                        <button
                            onClick={fetchData}
                            className="p-1.5 border border-slate-700 text-slate-400 hover:bg-slate-800"
                        >
                            <RefreshCw size={14} className={loadingProducts ? 'animate-spin' : ''} />
                        </button>
                    </div>
                </div>

                <div className="border border-slate-800 bg-slate-900/60 p-3 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-1 text-[10px] text-slate-400 flex-1">
                            <span>
                                {rows.length} / {allRows.length} records
                                {activeFilterCount > 0 && <span className="text-emerald-400"> filtered</span>}
                            </span>
                            <span className="font-mono-nums text-slate-200">
                                Value {formatCurrency(summary.totalValue)}
                            </span>
                            <span className={`font-mono-nums ${kind === 'asset' ? 'text-cyan-400' : 'text-amber-400'}`}>
                                {kind === 'asset' ? 'Monthly Dep.' : 'Monthly Cost'} {formatCurrency(summary.monthlyTotal)}
                            </span>
                        </div>
                        <button
                            type="button"
                            onClick={() => setShowProductFilters((prev) => ({ ...prev, [kind]: !prev[kind] }))}
                            className={`p-1.5 border text-slate-300 hover:text-emerald-300 ${showProductFilters[kind] ? 'border-emerald-700 bg-emerald-950/30' : 'border-slate-700 bg-slate-800 hover:bg-slate-700'}`}
                            aria-label={`Toggle ${kind} filters`}
                            title={`${title} filters`}
                        >
                            <SlidersHorizontal size={14} />
                        </button>
                    </div>

                    {showProductFilters[kind] && (
                        <>
                            <div className="grid grid-cols-2 xl:grid-cols-5 gap-2">
                                <input
                                    type="text"
                                    value={draft.q}
                                    onChange={(event) => setProductFilterDraft(kind, 'q', event.target.value)}
                                    placeholder="Name / memo"
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                                <select
                                    value={draft.category}
                                    onChange={(event) => setProductFilterDraft(kind, 'category', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title="Budget category"
                                >
                                    <option value="">All categories</option>
                                    {categoryOptions.map((category) => (
                                        <option key={category} value={category}>{category}</option>
                                    ))}
                                </select>
                                <select
                                    value={draft.budgetAccountId}
                                    onChange={(event) => setProductFilterDraft(kind, 'budgetAccountId', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title="Budget account"
                                >
                                    <option value="">All budgets</option>
                                    {budgetOptions.map(([id, name]) => (
                                        <option key={id} value={id}>{name}</option>
                                    ))}
                                </select>
                                <select
                                    value={draft.fundingCapsuleId}
                                    onChange={(event) => setProductFilterDraft(kind, 'fundingCapsuleId', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title="Funding capsule"
                                >
                                    <option value="">All capsules</option>
                                    {fundingOptions.map(([id, name]) => (
                                        <option key={id} value={id}>{name}</option>
                                    ))}
                                </select>
                                <select
                                    value={draft.treatment}
                                    onChange={(event) => setProductFilterDraft(kind, 'treatment', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title="Budget treatment"
                                >
                                    <option value="">All treatments</option>
                                    {treatmentOptions.map((treatment) => (
                                        <option key={treatment} value={treatment}>{treatment.replace('_', ' ')}</option>
                                    ))}
                                </select>
                                <select
                                    value={draft.location}
                                    onChange={(event) => setProductFilterDraft(kind, 'location', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title="Location"
                                >
                                    <option value="">All locations</option>
                                    {locationOptions.map((location) => (
                                        <option key={location} value={location}>{location}</option>
                                    ))}
                                </select>
                                <input
                                    type="date"
                                    value={draft.dateFrom}
                                    onChange={(event) => setProductFilterDraft(kind, 'dateFrom', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title={kind === 'asset' ? 'Purchase date from' : 'Next purchase from'}
                                />
                                <input
                                    type="date"
                                    value={draft.dateTo}
                                    onChange={(event) => setProductFilterDraft(kind, 'dateTo', event.target.value)}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                    title={kind === 'asset' ? 'Purchase date to' : 'Next purchase to'}
                                />
                                <input
                                    type="number"
                                    value={draft.amountMin}
                                    onChange={(event) => setProductFilterDraft(kind, 'amountMin', event.target.value)}
                                    placeholder="Min price"
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                                <input
                                    type="number"
                                    value={draft.amountMax}
                                    onChange={(event) => setProductFilterDraft(kind, 'amountMax', event.target.value)}
                                    placeholder="Max price"
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                            </div>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex flex-wrap gap-1 text-[10px] text-slate-500">
                                    {summary.categoryBreakdown.slice(0, 4).map((row) => (
                                        <span key={row.category} className="border border-slate-700 bg-slate-950/50 px-2 py-1">
                                            {row.category}: {row.count} / {formatCurrency(row.value)}
                                        </span>
                                    ))}
                                    {rows.length === 0 && <span>No matching records</span>}
                                </div>
                                <div className="flex gap-2">
                                    <button onClick={() => applyProductFilters(kind)} className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-[10px] font-bold">Apply</button>
                                    <button onClick={() => clearProductFilters(kind)} className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-bold">Clear</button>
                                </div>
                            </div>
                        </>
                    )}
                    {!showProductFilters[kind] && summary.categoryBreakdown.length > 0 && (
                        <div className="flex flex-wrap gap-1 border-t border-slate-800 pt-2 text-[10px] text-slate-500">
                            {summary.categoryBreakdown.slice(0, 4).map((row) => (
                                <span key={row.category} className="border border-slate-800 bg-slate-950/40 px-2 py-1">
                                    {row.category}: {row.count}
                                </span>
                            ))}
                        </div>
                    )}
                </div>

                <div className="border border-slate-800 overflow-auto">
                    <table className="w-full text-xs">
                        <thead className="bg-slate-900 sticky top-0">
                            <tr className="border-b border-slate-800">
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Name</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Budget / Category</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Treatment</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Funding Capsule</th>
                                <th className="p-2 text-right text-slate-500 uppercase font-medium">Reserve / Mo</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Location</th>
                                <th className="p-2 text-right text-slate-500 uppercase font-medium">Price</th>
                                <th className="p-2 text-right text-slate-500 uppercase font-medium">{kind === 'asset' ? 'Monthly Dep.' : 'Monthly Cost'}</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">{kind === 'asset' ? 'Purchase Date' : 'Next Purchase'}</th>
                                <th className="p-2" />
                            </tr>
                        </thead>
                        <tbody>
                            {loadingProducts ? (
                                <tr><td colSpan={10} className="p-4 text-slate-500">Loading...</td></tr>
                            ) : rows.length === 0 ? (
                                <tr><td colSpan={10} className="p-6 text-center text-slate-500">No matching records.</td></tr>
                            ) : (
                                rows.map((product) => {
                                    const price = productPrice(product);
                                    const monthlyValue = productMonthlyValue(product, kind);

                                    return (
                                        <tr key={product.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 group">
                                            <td className="p-2">
                                                <div className="flex items-center gap-2">
                                                    {kind === 'asset'
                                                        ? <Cpu size={12} className="text-emerald-400" />
                                                        : <Package size={12} className="text-cyan-400" />}
                                                    <span className="text-slate-200">{product.name}</span>
                                                </div>
                                            </td>
                                            <td className="p-2 text-slate-500">{productCategoryLabel(product)}</td>
                                            <td className="p-2 text-slate-500">
                                                <div className="space-y-0.5">
                                                    <p>{productTreatment(product).replace('_', ' ')}</p>
                                                    {product.budget_treatment === 'auto' && <p className="text-[9px] text-slate-600">Auto</p>}
                                                </div>
                                            </td>
                                            <td className="p-2 text-slate-500">{product.funding_capsule_name || '-'}</td>
                                            <td className="p-2 text-right font-mono-nums text-purple-300">{formatCurrency(product.recommended_monthly_reserve ?? 0)}</td>
                                            <td className="p-2 text-slate-500">{product.location || '-'}</td>
                                            <td className="p-2 text-right font-mono-nums text-slate-300">{formatCurrency(price)}</td>
                                            <td className="p-2 text-right font-mono-nums text-cyan-400">
                                                {formatCurrency(monthlyValue)}
                                            </td>
                                            <td className="p-2 text-slate-500">
                                                {productDate(product, kind) || '-'}
                                            </td>
                                            <td className="p-2 text-right">
                                                <button
                                                    onClick={() => setProductModal({ type: kind, product })}
                                                    className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-slate-200"
                                                >
                                                    <Edit size={11} />
                                                </button>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    };

    const renderExchangeRates = () => (
        <div className="space-y-4">
            <div>
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <h2 className="text-sm font-semibold">Exchange Rates</h2>
                        <p className="text-[10px] text-slate-500">
                            Valuation rates used to convert journal currencies into the client base currency.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => handleAutoUpdateRates(false)}
                        disabled={autoUpdatingRates}
                        className="px-3 py-1.5 border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-50 text-xs flex items-center gap-1"
                    >
                        <RefreshCw size={12} className={autoUpdatingRates ? 'animate-spin' : ''} />
                        Auto Update
                    </button>
                </div>
                {lastRateUpdate && (
                    <p className="mt-2 text-[10px] text-slate-500">
                        Last auto check: updated {lastRateUpdate.updated}, skipped {lastRateUpdate.skipped}, errors {lastRateUpdate.errors}
                    </p>
                )}
            </div>

            <div className="border border-slate-800 p-3">
                <div className="grid grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto] gap-2">
                    <input
                        value={rateDraft.base_currency}
                        onChange={(event) => setRateDraft({ ...rateDraft, base_currency: event.target.value })}
                        className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs uppercase"
                        placeholder="USD"
                    />
                    <input
                        value={rateDraft.quote_currency}
                        onChange={(event) => setRateDraft({ ...rateDraft, quote_currency: event.target.value })}
                        className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs uppercase"
                        placeholder={currentClient?.general_settings?.currency || 'JPY'}
                    />
                    <input
                        type="number"
                        value={rateDraft.rate}
                        onChange={(event) => setRateDraft({ ...rateDraft, rate: event.target.value })}
                        className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                        placeholder="Rate"
                    />
                    <input
                        type="date"
                        value={rateDraft.as_of_date}
                        onChange={(event) => setRateDraft({ ...rateDraft, as_of_date: event.target.value })}
                        className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                    />
                    <input
                        value={rateDraft.source}
                        onChange={(event) => setRateDraft({ ...rateDraft, source: event.target.value })}
                        className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                        placeholder="manual"
                    />
                    <button
                        type="button"
                        disabled={isSavingRate}
                        onClick={handleAddRate}
                        className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-3 py-1.5 text-xs font-semibold text-white"
                    >
                        {isSavingRate ? 'Saving...' : 'Add Rate'}
                    </button>
                </div>
            </div>

            <div className="border border-slate-800 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900">
                        <tr className="border-b border-slate-800">
                            <th className="p-2 text-left text-slate-500 uppercase font-medium">Pair</th>
                            <th className="p-2 text-right text-slate-500 uppercase font-medium">Rate</th>
                            <th className="p-2 text-left text-slate-500 uppercase font-medium">As Of</th>
                            <th className="p-2 text-left text-slate-500 uppercase font-medium">Source</th>
                            <th className="p-2" />
                        </tr>
                    </thead>
                    <tbody>
                        {exchangeRates.length === 0 ? (
                            <tr>
                                <td colSpan={5} className="p-6 text-center text-slate-500">No exchange rates configured.</td>
                            </tr>
                        ) : (
                            exchangeRates.map((rate) => (
                                <tr key={rate.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 group">
                                    <td className="p-2 font-mono text-slate-200">{rate.base_currency}/{rate.quote_currency}</td>
                                    <td className="p-2 text-right font-mono-nums text-emerald-300">{rate.rate}</td>
                                    <td className="p-2 font-mono text-slate-500">{rate.as_of_date}</td>
                                    <td className="p-2 text-slate-400">{rate.source || 'manual'}</td>
                                    <td className="p-2 text-right">
                                        <button
                                            type="button"
                                            onClick={() => handleDeleteRate(rate.id)}
                                            className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-300"
                                            title="Delete rate"
                                        >
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

    const renderRegistryTab = (entryType: string) => {
        const sourceAccounts = accounts.filter((a) => a.account_type === 'asset');
        const budgetAccounts = accounts.filter((a) => a.account_type === 'expense' || a.account_type === 'liability');
        const destinationAccounts = accounts.filter((a) => ['asset', 'liability', 'expense'].includes(a.account_type));
        const allRows = registryEntries.filter((e) => e.entry_type === entryType);
        const filtered = allRows.filter((e) => {
            if (sourcesFilter.q && !e.name.toLowerCase().includes(sourcesFilter.q.toLowerCase())) return false;
            if (sourcesFilter.budgetAccountId && String(e.budget_account_id ?? '') !== sourcesFilter.budgetAccountId) return false;
            return true;
        });
        const activeFilterCount = Object.values(sourcesFilter).filter(Boolean).length;

        return (
            <div className="space-y-4">
                <div className="border border-slate-800 bg-slate-900/60 p-3 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-[10px] text-slate-400">
                            {filtered.length}{allRows.length !== filtered.length && ` / ${allRows.length}`} entries
                            {activeFilterCount > 0 && <span className="text-emerald-400 ml-1">filtered</span>}
                        </span>
                        <div className="flex gap-2">
                            <button
                                type="button"
                                onClick={() => setShowSourcesFilter((v) => !v)}
                                className={`p-1.5 border text-slate-300 hover:text-emerald-300 ${showSourcesFilter ? 'border-emerald-700 bg-emerald-950/30' : 'border-slate-700 bg-slate-800 hover:bg-slate-700'}`}
                                title="Toggle filter"
                            >
                                <SlidersHorizontal size={14} />
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    setEditingRegistryId(null);
                                    setRegistryForm({ ...EMPTY_REGISTRY_FORM, ...(TAB_DEFAULTS[entryType] ?? {}), currency: currentClient?.general_settings?.currency || 'JPY' });
                                    setShowRegistryForm((v) => !v);
                                }}
                                className="flex items-center gap-1 bg-cyan-700 px-3 py-1.5 text-xs text-white hover:bg-cyan-600"
                            >
                                <Plus size={13} /> Add
                            </button>
                        </div>
                    </div>

                    {showSourcesFilter && (
                        <div className="space-y-2 pt-1 border-t border-slate-700">
                            <div className="grid grid-cols-2 gap-2">
                                <input
                                    type="text"
                                    value={sourcesFilterDraft.q}
                                    onChange={(e) => setSourcesFilterDraft((prev) => ({ ...prev, q: e.target.value }))}
                                    placeholder="Name"
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                                <select
                                    value={sourcesFilterDraft.budgetAccountId}
                                    onChange={(e) => setSourcesFilterDraft((prev) => ({ ...prev, budgetAccountId: e.target.value }))}
                                    className="bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs"
                                >
                                    <option value="">Budget account...</option>
                                    {budgetAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                                </select>
                            </div>
                            <div className="flex gap-2 justify-end">
                                <button
                                    type="button"
                                    onClick={() => setSourcesFilter({ ...sourcesFilterDraft })}
                                    className="bg-cyan-700 px-3 py-1 text-xs text-white hover:bg-cyan-600"
                                >Apply</button>
                                <button
                                    type="button"
                                    onClick={() => { const c = { q: '', budgetAccountId: '' }; setSourcesFilter(c); setSourcesFilterDraft(c); }}
                                    className="bg-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-600"
                                >Clear</button>
                            </div>
                        </div>
                    )}
                </div>

                {showRegistryForm && (
                    <div className="border border-cyan-900/50 bg-cyan-950/10 p-3 space-y-3">
                        <div className="grid grid-cols-6 gap-2">
                            <input value={registryForm.name} onChange={(event) => setRegistryForm({ ...registryForm, name: event.target.value })} placeholder="Name" className="col-span-2 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                            <select value={registryForm.entry_type} onChange={(event) => setRegistryForm({ ...registryForm, entry_type: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="service">Service</option>
                                <option value="income">Income</option>
                                <option value="allocation">Allocation</option>
                                <option value="debt">Debt</option>
                                <option value="item">Item</option>
                                <option value="asset">Asset</option>
                            </select>
                            <select value={registryForm.line_type} onChange={(event) => setRegistryForm({ ...registryForm, line_type: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="expense">Expense</option>
                                <option value="income">Income</option>
                                <option value="allocation">Allocation</option>
                                <option value="debt_payment">Debt</option>
                                <option value="borrowing">Borrowing</option>
                                <option value="drawdown">Drawdown</option>
                            </select>
                            <input type="number" value={registryForm.amount} onChange={(event) => setRegistryForm({ ...registryForm, amount: event.target.value })} placeholder="Amount" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                            <input value={registryForm.currency} onChange={(event) => setRegistryForm({ ...registryForm, currency: event.target.value })} placeholder="JPY" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                            <select value={registryForm.frequency} onChange={(event) => setRegistryForm({ ...registryForm, frequency: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="Monthly">Monthly</option>
                                <option value="Yearly">Yearly</option>
                                <option value="EveryNDays">Every N Days</option>
                                <option value="Irregular">Irregular</option>
                            </select>
                            {registryForm.frequency === 'EveryNDays' ? (
                                <input type="number" value={registryForm.frequency_days} onChange={(event) => setRegistryForm({ ...registryForm, frequency_days: event.target.value })} placeholder="Days" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                            ) : registryForm.frequency === 'Yearly' ? (
                                <input type="number" min="1" max="12" value={registryForm.month_of_year} onChange={(event) => setRegistryForm({ ...registryForm, month_of_year: event.target.value })} placeholder="Month" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                            ) : (
                                <input type="number" min="1" max="31" value={registryForm.day_of_month} onChange={(event) => setRegistryForm({ ...registryForm, day_of_month: event.target.value })} placeholder="Day" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                            )}
                            <select value={registryForm.source_account_id} onChange={(event) => setRegistryForm({ ...registryForm, source_account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="">Source...</option>
                                {sourceAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                            </select>
                            <select value={registryForm.budget_account_id} onChange={(event) => setRegistryForm({ ...registryForm, budget_account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="">Budget target...</option>
                                {budgetAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                            </select>
                            <select value={registryForm.destination_account_id} onChange={(event) => setRegistryForm({ ...registryForm, destination_account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                <option value="">Destination...</option>
                                {destinationAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                            </select>
                            <input type="month" value={registryForm.start_period} onChange={(event) => setRegistryForm({ ...registryForm, start_period: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                            <input type="month" value={registryForm.end_period} onChange={(event) => setRegistryForm({ ...registryForm, end_period: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="flex flex-wrap gap-4 text-xs text-slate-300">
                                <label className="flex items-center gap-2"><input type="checkbox" checked={registryForm.budget_active} onChange={(event) => setRegistryForm({ ...registryForm, budget_active: event.target.checked })} /> Budget active</label>
                                <label className="flex items-center gap-2"><input type="checkbox" checked={registryForm.generate_recurring} onChange={(event) => setRegistryForm({ ...registryForm, generate_recurring: event.target.checked })} /> Generate recurring</label>
                                <label className="flex items-center gap-2"><input type="checkbox" checked={registryForm.is_active} onChange={(event) => setRegistryForm({ ...registryForm, is_active: event.target.checked })} /> Active</label>
                            </div>
                            <div className="flex gap-2">
                                <button type="button" onClick={saveRegistryEntry} className="bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-600">{editingRegistryId ? 'Update' : 'Create'}</button>
                                <button type="button" onClick={resetRegistryForm} className="bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700">Cancel</button>
                            </div>
                        </div>
                    </div>
                )}

                <div className="border border-slate-800 overflow-auto">
                    <table className="w-full text-[10px]">
                        <thead className="bg-slate-900 text-slate-500 uppercase">
                            <tr>
                                <th className="p-2 text-left font-normal">Name</th>
                                <th className="p-2 text-right font-normal">Amount</th>
                                <th className="p-2 text-left font-normal">Frequency</th>
                                <th className="p-2 text-left font-normal">Budget Target</th>
                                <th className="p-2 text-left font-normal">Flags</th>
                                <th className="p-2" />
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map((entry) => (
                                <tr key={entry.id} className="border-t border-slate-800 hover:bg-slate-800/30">
                                    <td className="p-2 text-slate-200">{entry.name}</td>
                                    <td className="p-2 text-right font-mono-nums text-cyan-300">{formatCurrency(entry.amount)}</td>
                                    <td className="p-2 text-slate-400">{entry.frequency}</td>
                                    <td className="p-2 text-slate-400">{entry.budget_account_name || entry.destination_account_name || entry.source_account_name || '-'}</td>
                                    <td className="p-2 space-x-1">
                                        {entry.budget_active && <span className="text-emerald-600">budget</span>}
                                        {entry.generate_recurring && <span className="text-cyan-700">recur</span>}
                                        {!entry.is_active && <span className="text-rose-700">inactive</span>}
                                    </td>
                                    <td className="p-2 text-right">
                                        <button type="button" onClick={() => editRegistryEntry(entry)} className="p-1 text-slate-500 hover:text-cyan-400" title="Edit"><Edit size={12} /></button>
                                        <button type="button" onClick={() => removeRegistryEntry(entry)} className="p-1 text-slate-500 hover:text-rose-400" title="Delete"><Trash2 size={12} /></button>
                                    </td>
                                </tr>
                            ))}
                            {filtered.length === 0 && (
                                <tr><td colSpan={6} className="p-4 text-center text-slate-600">No entries</td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    };

    const renderSources = () => (
        <div className="space-y-4">
            <div className="flex border-b border-slate-700">
                {SOURCES_INNER_TABS.map((tab) => (
                    <button
                        key={tab.id}
                        type="button"
                        onClick={() => { setSourcesTab(tab.id); setShowRegistryForm(false); }}
                        className={`px-4 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
                            sourcesTab === tab.id
                                ? 'border-cyan-500 text-cyan-300'
                                : 'border-transparent text-slate-500 hover:text-slate-300'
                        }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>
            <div>
                {sourcesTab === 'assets' && renderProducts('asset')}
                {sourcesTab === 'items' && renderProducts('item')}
                {sourcesTab !== 'assets' && sourcesTab !== 'items' && renderRegistryTab(sourcesTab)}
            </div>
        </div>
    );

    const renderAccounts = () => {
        const renderNode = (account: AccountTreeNode, depth: number) => {
            const parentOptions = accounts.filter((candidate) => (
                candidate.account_type === account.account_type && candidate.id !== account.id
            ));
            return (
                <div key={account.id} className="space-y-1">
                    <div className="flex items-center gap-2 py-1.5 px-2 bg-slate-800/30 border border-slate-700 group flex-wrap" style={{ marginLeft: depth * 18 }}>
                        {editingId === account.id ? (
                            <>
                                <input
                                    type="text"
                                    value={editForm.name ?? account.name}
                                    onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
                                    className="min-w-44 flex-1 bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs"
                                />
                                <select
                                    value={editForm.parent_id ?? account.parent_id ?? ''}
                                    onChange={(event) => setEditForm({ ...editForm, parent_id: event.target.value === '' ? null : Number(event.target.value) })}
                                    className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs text-slate-200"
                                >
                                    <option value="">No parent</option>
                                    {parentOptions.map((candidate) => (
                                        <option key={candidate.id} value={candidate.id}>{candidate.name}</option>
                                    ))}
                                </select>
                                {account.account_type === 'asset' && (
                                    <>
                                        <select
                                            value={editForm.role ?? account.role ?? 'unassigned'}
                                            onChange={(event) => setEditForm({ ...editForm, role: event.target.value as AccountRole })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs text-slate-200"
                                        >
                                            {ACCOUNT_ROLES.map((role) => (
                                                <option key={role.value} value={role.value}>{role.label}</option>
                                            ))}
                                        </select>
                                        <input
                                            type="number"
                                            min="0"
                                            placeholder="Target"
                                            value={editForm.role_target_amount ?? account.role_target_amount ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, role_target_amount: event.target.value === '' ? null : Number(event.target.value) })}
                                            className="w-28 bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                    </>
                                )}
                                {account.account_type === 'liability' && (
                                    <div className="grid w-full grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-1">
                                        <input
                                            type="number"
                                            min="1"
                                            max="31"
                                            placeholder="Close day"
                                            value={editForm.liability_closing_day ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, liability_closing_day: nullableNumber(event.target.value) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                        <input
                                            type="number"
                                            min="1"
                                            max="31"
                                            placeholder="Pay day"
                                            value={editForm.liability_payment_day ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, liability_payment_day: nullableNumber(event.target.value) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                        <input
                                            type="number"
                                            min="0"
                                            max="24"
                                            placeholder="Offset"
                                            value={editForm.liability_payment_month_offset ?? 0}
                                            onChange={(event) => setEditForm({ ...editForm, liability_payment_month_offset: Number(event.target.value || 0) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                        <select
                                            value={editForm.liability_payment_policy ?? 'full'}
                                            onChange={(event) => setEditForm({ ...editForm, liability_payment_policy: event.target.value as LiabilityPaymentPolicy })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs text-slate-200"
                                        >
                                            {LIABILITY_POLICIES.map((policy) => (
                                                <option key={policy.value} value={policy.value}>{policy.label}</option>
                                            ))}
                                        </select>
                                        <input
                                            type="number"
                                            min="0"
                                            placeholder="Min pay"
                                            value={editForm.liability_minimum_payment ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, liability_minimum_payment: nullableNumber(event.target.value) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                        <input
                                            type="number"
                                            min="0"
                                            placeholder="Fixed pay"
                                            value={editForm.liability_fixed_payment_amount ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, liability_fixed_payment_amount: nullableNumber(event.target.value) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                        <input
                                            type="number"
                                            min="1"
                                            placeholder="Installments"
                                            value={editForm.liability_installment_months ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, liability_installment_months: nullableNumber(event.target.value) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                        <input
                                            type="number"
                                            min="0"
                                            placeholder="Revo %"
                                            value={editForm.liability_revolving_rate ?? ''}
                                            onChange={(event) => setEditForm({ ...editForm, liability_revolving_rate: nullableNumber(event.target.value) })}
                                            className="bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                        />
                                    </div>
                                )}
                                <button onClick={() => handleUpdateAccount(account.id)} className="p-1 text-emerald-400 hover:bg-slate-700">
                                    <Save size={12} />
                                </button>
                                <button onClick={() => setEditingId(null)} className="p-1 text-slate-400 hover:bg-slate-700">
                                    <X size={12} />
                                </button>
                            </>
                        ) : (
                            <>
                                <span className="flex-1 text-xs capitalize">{account.name.replace(/_/g, ' ')}</span>
                                {account.account_type === 'asset' && (
                                    <span className="text-[10px] px-1.5 py-0.5 border border-slate-700 text-cyan-300 bg-slate-900/60 capitalize">
                                        {account.role || 'unassigned'}
                                    </span>
                                )}
                                {account.account_type === 'liability' && (
                                    <span className="text-[10px] px-1.5 py-0.5 border border-slate-700 text-amber-300 bg-slate-900/60">
                                        {account.liability_payment_policy || 'full'} / +{account.liability_payment_month_offset ?? 0}m
                                        {account.liability_closing_day ? ` / close ${account.liability_closing_day}` : ''}
                                        {account.liability_payment_day ? ` / pay ${account.liability_payment_day}` : ''}
                                    </span>
                                )}
                                <span className="text-[10px] font-mono-nums text-slate-500">self {formatCurrency(account.balance)}</span>
                                <span className="text-xs font-mono-nums text-slate-300">rollup {formatCurrency(account.rollup_balance)}</span>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <button
                                        onClick={() => {
                                            setNewAccount({
                                                ...emptyAccountDraft(),
                                                account_type: account.account_type,
                                                parent_id: String(account.id),
                                            });
                                            setShowAddAccount(true);
                                        }}
                                        className="p-1 text-slate-500 hover:text-emerald-400 hover:bg-slate-700"
                                        title="Add child account"
                                    >
                                        <Plus size={10} />
                                    </button>
                                    <button
                                        onClick={() => {
                                            setEditingId(account.id);
                                            setEditForm({
                                                name: account.name,
                                                parent_id: account.parent_id ?? null,
                                                role: account.role || 'unassigned',
                                                role_target_amount: account.role_target_amount ?? null,
                                                liability_closing_day: account.liability_closing_day ?? null,
                                                liability_payment_day: account.liability_payment_day ?? null,
                                                liability_payment_month_offset: account.liability_payment_month_offset ?? 0,
                                                liability_payment_policy: account.liability_payment_policy ?? 'full',
                                                liability_minimum_payment: account.liability_minimum_payment ?? null,
                                                liability_fixed_payment_amount: account.liability_fixed_payment_amount ?? null,
                                                liability_installment_months: account.liability_installment_months ?? null,
                                                liability_revolving_rate: account.liability_revolving_rate ?? null,
                                            });
                                        }}
                                        className="p-1 text-slate-500 hover:text-white hover:bg-slate-700"
                                    >
                                        <Edit size={10} />
                                    </button>
                                    <button
                                        onClick={() => handleDeleteAccount(account.id)}
                                        className="p-1 text-slate-500 hover:text-rose-400 hover:bg-slate-700"
                                    >
                                        <Trash2 size={10} />
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                    {account.children.map((child) => renderNode(child, depth + 1))}
                </div>
            );
        };

        return (
        <div className="space-y-4">
            {ACCOUNT_TYPES.map((type) => {
                const typeAccounts = accounts.filter((account) => account.account_type === type.value);
                const treeNodes = accountTree[type.value] ?? [];
                return (
                    <div key={type.value} className="space-y-1">
                        <p className={`text-[10px] uppercase tracking-wider ${type.color} flex items-center gap-1`}>
                            <Wallet size={10} /> {type.label} Accounts ({typeAccounts.length})
                        </p>
                        {treeNodes.map((account) => renderNode(account, 0))}
                    </div>
                );
            })}

            {showAddAccount ? (
                <div className="border border-dashed border-emerald-700 p-3 space-y-2">
                    <div className="grid grid-cols-2 gap-2">
                        <input
                            type="text"
                            placeholder="Account name"
                            value={newAccount.name}
                            onChange={(event) => setNewAccount({ ...newAccount, name: event.target.value })}
                            className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                        />
                        <select
                            value={newAccount.account_type}
                            onChange={(event) => setNewAccount({ ...newAccount, account_type: event.target.value })}
                            className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                        >
                            {ACCOUNT_TYPES.map((type) => (
                                <option key={type.value} value={type.value}>{type.label}</option>
                            ))}
                        </select>
                        <select
                            value={newAccount.parent_id}
                            onChange={(event) => setNewAccount({ ...newAccount, parent_id: event.target.value })}
                            className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                        >
                            <option value="">No parent</option>
                            {accounts.filter((account) => account.account_type === newAccount.account_type).map((account) => (
                                <option key={account.id} value={account.id}>{account.name}</option>
                            ))}
                        </select>
                        {newAccount.account_type === 'asset' && (
                            <>
                                <select
                                    value={newAccount.role}
                                    onChange={(event) => setNewAccount({ ...newAccount, role: event.target.value as AccountRole })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                                >
                                    {ACCOUNT_ROLES.map((role) => (
                                        <option key={role.value} value={role.value}>{role.label}</option>
                                    ))}
                                </select>
                                <input
                                    type="number"
                                    min="0"
                                    placeholder="Role target"
                                    value={newAccount.role_target_amount}
                                    onChange={(event) => setNewAccount({ ...newAccount, role_target_amount: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                            </>
                        )}
                        {newAccount.account_type === 'liability' && (
                            <>
                                <input
                                    type="number"
                                    min="1"
                                    max="31"
                                    placeholder="Closing day"
                                    value={newAccount.liability_closing_day}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_closing_day: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                                <input
                                    type="number"
                                    min="1"
                                    max="31"
                                    placeholder="Payment day"
                                    value={newAccount.liability_payment_day}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_payment_day: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                                <input
                                    type="number"
                                    min="0"
                                    max="24"
                                    placeholder="Month offset"
                                    value={newAccount.liability_payment_month_offset}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_payment_month_offset: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                                <select
                                    value={newAccount.liability_payment_policy}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_payment_policy: event.target.value as LiabilityPaymentPolicy })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                                >
                                    {LIABILITY_POLICIES.map((policy) => (
                                        <option key={policy.value} value={policy.value}>{policy.label}</option>
                                    ))}
                                </select>
                                <input
                                    type="number"
                                    min="0"
                                    placeholder="Minimum payment"
                                    value={newAccount.liability_minimum_payment}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_minimum_payment: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                                <input
                                    type="number"
                                    min="0"
                                    placeholder="Fixed payment"
                                    value={newAccount.liability_fixed_payment_amount}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_fixed_payment_amount: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                                <input
                                    type="number"
                                    min="1"
                                    placeholder="Installment months"
                                    value={newAccount.liability_installment_months}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_installment_months: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                                <input
                                    type="number"
                                    min="0"
                                    placeholder="Revolving %"
                                    value={newAccount.liability_revolving_rate}
                                    onChange={(event) => setNewAccount({ ...newAccount, liability_revolving_rate: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                />
                            </>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button onClick={handleAddAccount} className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-1.5 text-xs">
                            Create Account
                        </button>
                        <button onClick={() => setShowAddAccount(false)} className="px-3 bg-slate-700 hover:bg-slate-600 text-white py-1.5 text-xs">
                            Cancel
                        </button>
                    </div>
                </div>
            ) : (
                <button
                    onClick={() => setShowAddAccount(true)}
                    className="w-full border border-dashed border-slate-700 hover:border-emerald-600 p-2 text-xs text-slate-500 hover:text-emerald-400 flex items-center justify-center gap-1"
                >
                    <Plus size={12} /> Add Account
                </button>
            )}
        </div>
        );
    };

    return (
        <div className="h-full p-4 overflow-auto">
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                <div className="p-4">
                    {activeTab === 'accounts' && renderAccounts()}
                    {activeTab === 'exchange-rates' && renderExchangeRates()}
                    {activeTab === 'sources' && renderSources()}
                </div>
            </TabPanel>

            {productModal && (
                <ProductModal
                    initialType={productModal.type}
                    product={productModal.product}
                    budgetAccounts={accounts.filter((account) => account.account_type === 'expense')}
                    fundingCapsules={capsules.filter((capsule) => capsule.life_event_id == null)}
                    onClose={() => setProductModal(null)}
                    onSaved={fetchData}
                />
            )}
        </div>
    );
}
