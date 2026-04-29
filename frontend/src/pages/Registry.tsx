import { useEffect, useMemo, useState } from 'react';
import { Cpu, Edit, Package, Plus, RefreshCw, Save, Trash2, Wallet, X } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import {
    createAccount,
    createProduct,
    deleteAccount,
    deleteProduct,
    getAccounts,
    getProducts,
    getUnitEconomicsSummary,
    seedDefaultAccounts,
    updateAccount,
    updateProduct,
} from '../api';
import { useToast } from '../components/Toast';
import type { Product } from '../types';

const TABS = [
    { id: 'accounts', label: 'Accounts' },
    { id: 'assets', label: 'Assets' },
    { id: 'items', label: 'Items' },
];

const ACCOUNT_TYPES = [
    { value: 'asset', label: 'Asset', color: 'text-emerald-400' },
    { value: 'liability', label: 'Liability', color: 'text-rose-400' },
    { value: 'income', label: 'Income', color: 'text-cyan-400' },
    { value: 'expense', label: 'Expense', color: 'text-amber-400' },
];

const EMPTY_PRODUCT_FORM = {
    name: '',
    category: 'Uncategorized',
    location: '',
    is_asset: true,
    purchase_price: '',
    purchase_date: '',
    lifespan_months: '',
    last_unit_price: '',
    units_per_purchase: '1',
    frequency_days: '',
    last_purchase_date: '',
};

type ProductForm = typeof EMPTY_PRODUCT_FORM;

function productToForm(product: Product): ProductForm {
    return {
        name: product.name ?? '',
        category: product.category ?? 'Uncategorized',
        location: product.location ?? '',
        is_asset: product.is_asset ?? true,
        purchase_price: product.purchase_price != null ? String(product.purchase_price) : '',
        purchase_date: product.purchase_date ?? '',
        lifespan_months: product.lifespan_months != null ? String(product.lifespan_months) : '',
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
        purchase_price: purchasePrice,
        purchase_date: form.purchase_date || null,
    };
}

interface ProductModalProps {
    initialType: 'asset' | 'item';
    product: Product | null;
    onClose: () => void;
    onSaved: () => void;
}

function ProductModal({ initialType, product, onClose, onSaved }: ProductModalProps) {
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
                            'Category',
                            <input
                                className={inputClass}
                                value={form.category}
                                onChange={(event) => set('category', event.target.value)}
                                placeholder="Electronics"
                            />
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
    const [unitSummary, setUnitSummary] = useState<any>(null);
    const [accounts, setAccounts] = useState<any[]>([]);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editForm, setEditForm] = useState<any>({});
    const [newAccount, setNewAccount] = useState({ name: '', account_type: 'expense', budget_limit: '' });
    const [showAddAccount, setShowAddAccount] = useState(false);
    const [productModal, setProductModal] = useState<{ type: 'asset' | 'item'; product: Product | null } | null>(null);
    const [loadingProducts, setLoadingProducts] = useState(false);
    const { showToast } = useToast();

    const assets = useMemo(() => products.filter((product) => product.is_asset), [products]);
    const items = useMemo(() => products.filter((product) => !product.is_asset), [products]);

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        try {
            setLoadingProducts(true);
            const [productsData, summaryData, accountsData] = await Promise.all([
                getProducts(),
                getUnitEconomicsSummary(),
                getAccounts(),
            ]);
            setProducts(productsData);
            setUnitSummary(summaryData);
            setAccounts(accountsData);
        } catch (error) {
            console.error('Failed to fetch registry data:', error);
            try {
                await seedDefaultAccounts();
                setAccounts(await getAccounts());
            } catch {
                showToast('Failed to load registry data', 'error');
            }
        } finally {
            setLoadingProducts(false);
        }
    };

    const formatCurrency = (value: number | null | undefined) => `¥${Math.round(value ?? 0).toLocaleString()}`;

    const handleAddAccount = async () => {
        if (!newAccount.name.trim()) return;
        try {
            await createAccount({
                name: newAccount.name.toLowerCase().replace(/\s+/g, '_'),
                account_type: newAccount.account_type,
                budget_limit: newAccount.budget_limit ? parseFloat(newAccount.budget_limit) : undefined,
            });
            showToast(`Account "${newAccount.name}" created`, 'success');
            setNewAccount({ name: '', account_type: 'expense', budget_limit: '' });
            setShowAddAccount(false);
            fetchData();
        } catch (error) {
            showToast('Failed to create account', 'error');
        }
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

    const renderProducts = (kind: 'asset' | 'item') => {
        const rows = kind === 'asset' ? assets : items;
        const title = kind === 'asset' ? 'Fixed Assets' : 'Consumable Items';

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

                <div className="grid grid-cols-3 gap-0 border border-slate-800">
                    <div className="border-r border-slate-800 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Records</p>
                        <p className="text-xl font-mono-nums text-slate-200">{rows.length}</p>
                    </div>
                    <div className="border-r border-slate-800 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">{kind === 'asset' ? 'Asset Value' : 'Monthly Cost'}</p>
                        <p className={`text-xl font-mono-nums ${kind === 'asset' ? 'text-emerald-400' : 'text-amber-400'}`}>
                            {kind === 'asset'
                                ? formatCurrency(rows.reduce((sum, item) => sum + (item.purchase_price ?? item.last_unit_price ?? 0), 0))
                                : formatCurrency(unitSummary?.total_monthly_cost ?? 0)}
                        </p>
                    </div>
                    <div className="p-3">
                        <p className="text-[10px] text-slate-500 uppercase">{kind === 'asset' ? 'Monthly Depreciation' : 'Top Category'}</p>
                        <p className="text-xl font-mono-nums text-cyan-400">
                            {kind === 'asset'
                                ? formatCurrency(rows.reduce((sum, item) => {
                                    const price = item.purchase_price ?? item.last_unit_price ?? 0;
                                    return sum + (item.lifespan_months ? price / item.lifespan_months : 0);
                                }, 0))
                                : unitSummary?.category_breakdown?.[0]?.category ?? '-'}
                        </p>
                    </div>
                </div>

                <div className="border border-slate-800 overflow-auto">
                    <table className="w-full text-xs">
                        <thead className="bg-slate-900 sticky top-0">
                            <tr className="border-b border-slate-800">
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Name</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Category</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">Location</th>
                                <th className="p-2 text-right text-slate-500 uppercase font-medium">Price</th>
                                <th className="p-2 text-right text-slate-500 uppercase font-medium">{kind === 'asset' ? 'Monthly Dep.' : 'Monthly Cost'}</th>
                                <th className="p-2 text-left text-slate-500 uppercase font-medium">{kind === 'asset' ? 'Purchase Date' : 'Next Purchase'}</th>
                                <th className="p-2" />
                            </tr>
                        </thead>
                        <tbody>
                            {loadingProducts ? (
                                <tr><td colSpan={7} className="p-4 text-slate-500">Loading...</td></tr>
                            ) : rows.length === 0 ? (
                                <tr><td colSpan={7} className="p-6 text-center text-slate-500">No records yet.</td></tr>
                            ) : (
                                rows.map((product) => {
                                    const price = product.purchase_price ?? product.last_unit_price ?? 0;
                                    const monthlyDep = product.lifespan_months ? price / product.lifespan_months : 0;

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
                                            <td className="p-2 text-slate-400">{product.category}</td>
                                            <td className="p-2 text-slate-500">{product.location || '-'}</td>
                                            <td className="p-2 text-right font-mono-nums text-slate-300">{formatCurrency(price)}</td>
                                            <td className="p-2 text-right font-mono-nums text-cyan-400">
                                                {kind === 'asset' ? formatCurrency(monthlyDep) : formatCurrency(product.monthly_cost)}
                                            </td>
                                            <td className="p-2 text-slate-500">
                                                {kind === 'asset'
                                                    ? product.purchase_date || product.last_purchase_date || '-'
                                                    : product.next_purchase_date || '-'}
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

                {kind === 'item' && (
                    <div className="border border-slate-800 p-3">
                        <p className="text-[10px] text-slate-500 uppercase mb-2">Top Consumable Categories</p>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            {(unitSummary?.category_breakdown ?? []).slice(0, 3).map((row: any) => (
                                <div key={row.category} className="bg-slate-900/60 border border-slate-700 p-2">
                                    <p className="text-xs text-slate-300">{row.category}</p>
                                    <p className="text-sm font-mono-nums text-amber-400">{formatCurrency(row.monthly_cost)} / mo</p>
                                </div>
                            ))}
                            {!unitSummary?.category_breakdown?.length && (
                                <p className="text-xs text-slate-500">Add replenishment frequency to see category run-rates.</p>
                            )}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    const renderAccounts = () => (
        <div className="space-y-4">
            {ACCOUNT_TYPES.map((type) => {
                const typeAccounts = accounts.filter((account) => account.account_type === type.value);
                return (
                    <div key={type.value} className="space-y-1">
                        <p className={`text-[10px] uppercase tracking-wider ${type.color} flex items-center gap-1`}>
                            <Wallet size={10} /> {type.label} Accounts ({typeAccounts.length})
                        </p>
                        {typeAccounts.map((account) => (
                            <div key={account.id} className="flex items-center gap-2 py-1.5 px-2 bg-slate-800/30 border border-slate-700 group">
                                {editingId === account.id ? (
                                    <>
                                        <input
                                            type="text"
                                            value={editForm.name ?? account.name}
                                            onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
                                            className="flex-1 bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs"
                                        />
                                        {type.value === 'expense' && (
                                            <input
                                                type="number"
                                                placeholder="Budget"
                                                value={editForm.budget_limit ?? account.budget_limit ?? ''}
                                                onChange={(event) => setEditForm({ ...editForm, budget_limit: event.target.value ? parseFloat(event.target.value) : null })}
                                                className="w-24 bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                            />
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
                                        <span className="text-xs font-mono-nums text-slate-400">{formatCurrency(account.balance)}</span>
                                        {type.value === 'expense' && account.budget_limit && (
                                            <span className="text-[10px] text-amber-400">Budget: {formatCurrency(account.budget_limit)}</span>
                                        )}
                                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <button
                                                onClick={() => {
                                                    setEditingId(account.id);
                                                    setEditForm({ name: account.name, budget_limit: account.budget_limit });
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
                        ))}
                    </div>
                );
            })}

            {showAddAccount ? (
                <div className="border border-dashed border-emerald-700 p-3 space-y-2">
                    <div className="grid grid-cols-3 gap-2">
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
                        {newAccount.account_type === 'expense' && (
                            <input
                                type="number"
                                placeholder="Monthly budget"
                                value={newAccount.budget_limit}
                                onChange={(event) => setNewAccount({ ...newAccount, budget_limit: event.target.value })}
                                className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                            />
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

    return (
        <div className="h-full p-4 overflow-auto">
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                <div className="p-4">
                    {activeTab === 'accounts' && renderAccounts()}
                    {activeTab === 'assets' && renderProducts('asset')}
                    {activeTab === 'items' && renderProducts('item')}
                </div>
            </TabPanel>

            {productModal && (
                <ProductModal
                    initialType={productModal.type}
                    product={productModal.product}
                    onClose={() => setProductModal(null)}
                    onSaved={fetchData}
                />
            )}
        </div>
    );
}
