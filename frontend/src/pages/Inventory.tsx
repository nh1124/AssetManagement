import { useState, useEffect } from 'react';
import { Package, Cpu, Wallet, Plus, Edit, Trash2, Save, X } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import { getProducts, getAccounts, createAccount, updateAccount, deleteAccount, updateProduct, seedDefaultAccounts } from '../api';
import { useToast } from '../components/Toast';

const TABS = [
    { id: 'items', label: 'Items' },
    { id: 'assets', label: 'Assets' },
    { id: 'accounts', label: 'Accounts' },
];

const ACCOUNT_TYPES = [
    { value: 'asset', label: 'Asset', color: 'text-emerald-400' },
    { value: 'liability', label: 'Liability', color: 'text-rose-400' },
    { value: 'income', label: 'Income', color: 'text-cyan-400' },
    { value: 'expense', label: 'Expense', color: 'text-amber-400' },
];

export default function Inventory() {
    const [activeTab, setActiveTab] = useState('items');
    const [products, setProducts] = useState<any[]>([]);
    const [accounts, setAccounts] = useState<any[]>([]);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editForm, setEditForm] = useState<any>({});
    const [newAccount, setNewAccount] = useState({ name: '', account_type: 'expense', budget_limit: '' });
    const [showAddAccount, setShowAddAccount] = useState(false);
    const { showToast } = useToast();

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        try {
            const [productsData, accountsData] = await Promise.all([
                getProducts(),
                getAccounts()
            ]);
            setProducts(productsData);
            setAccounts(accountsData);
        } catch (error) {
            console.error('Failed to fetch data:', error);
            // Seed default accounts if empty
            await seedDefaultAccounts();
            const accountsData = await getAccounts();
            setAccounts(accountsData);
        }
    };

    const formatCurrency = (value: number) => `¥${value.toLocaleString()}`;

    const handleUpdateProduct = async (id: number, data: any) => {
        try {
            await updateProduct(id, data);
            showToast('Product updated', 'success');
            fetchData();
        } catch (error) {
            showToast('Failed to update product', 'error');
        }
    };

    const handleAddAccount = async () => {
        if (!newAccount.name.trim()) return;
        try {
            await createAccount({
                name: newAccount.name.toLowerCase().replace(/\s+/g, '_'),
                account_type: newAccount.account_type,
                budget_limit: newAccount.budget_limit ? parseFloat(newAccount.budget_limit) : undefined
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

    const assetProducts = products.filter(p => p.is_asset && p.last_unit_price >= 30000);

    const renderTabContent = () => {
        switch (activeTab) {
            case 'items':
                return (
                    <div className="space-y-2">
                        <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">AI-Extracted Products</p>
                        {products.length === 0 ? (
                            <div className="text-center py-8 text-slate-600 text-xs">
                                No items yet. AI will extract products from receipts.
                            </div>
                        ) : (
                            products.filter(p => !p.is_asset || p.last_unit_price < 30000).map((product) => (
                                <div key={product.id} className="flex items-center justify-between py-2 px-2 bg-slate-800/30 border border-slate-700 hover:border-slate-600">
                                    <div className="flex items-center gap-2">
                                        <Package size={12} className="text-slate-500" />
                                        <div>
                                            <p className="text-xs">{product.name}</p>
                                            <p className="text-[10px] text-slate-600">{product.category} • {product.location || 'Unknown store'}</p>
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <p className="text-xs font-mono-nums">{formatCurrency(product.last_unit_price)}</p>
                                        <p className="text-[10px] text-slate-600">{product.last_purchase_date || 'No date'}</p>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                );

            case 'assets':
                return (
                    <div className="space-y-2">
                        <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">High-Value Items (≥¥30,000)</p>
                        {assetProducts.length === 0 ? (
                            <div className="text-center py-8 text-slate-600 text-xs">
                                No assets tracked. Items over ¥30,000 appear here.
                            </div>
                        ) : (
                            assetProducts.map((product) => (
                                <div key={product.id} className="bg-slate-800/30 border border-slate-700 p-3">
                                    <div className="flex items-center justify-between mb-2">
                                        <div className="flex items-center gap-2">
                                            <Cpu size={12} className="text-amber-400" />
                                            <span className="text-xs font-medium">{product.name}</span>
                                        </div>
                                        <span className="text-xs font-mono-nums text-emerald-400">{formatCurrency(product.purchase_price || product.last_unit_price)}</span>
                                    </div>
                                    <div className="grid grid-cols-3 gap-2 text-[10px]">
                                        <div>
                                            <p className="text-slate-500">Purchase Date</p>
                                            <p>{product.purchase_date || product.last_purchase_date || 'N/A'}</p>
                                        </div>
                                        <div>
                                            <p className="text-slate-500">Lifespan</p>
                                            <input
                                                type="number"
                                                placeholder="months"
                                                defaultValue={product.lifespan_months || ''}
                                                onBlur={(e) => {
                                                    if (e.target.value) {
                                                        handleUpdateProduct(product.id, { lifespan_months: parseInt(e.target.value), is_asset: true });
                                                    }
                                                }}
                                                className="w-full bg-slate-900 border border-slate-700 px-1 py-0.5 text-[10px] font-mono-nums"
                                            />
                                        </div>
                                        <div>
                                            <p className="text-slate-500">Monthly Depreciation</p>
                                            <p className="text-rose-400">
                                                {product.lifespan_months
                                                    ? formatCurrency((product.purchase_price || product.last_unit_price) / product.lifespan_months)
                                                    : 'Set lifespan'}
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                );

            case 'accounts':
                return (
                    <div className="space-y-4">
                        {ACCOUNT_TYPES.map((type) => {
                            const typeAccounts = accounts.filter(a => a.account_type === type.value);
                            return (
                                <div key={type.value} className="space-y-1">
                                    <p className={`text-[10px] uppercase tracking-wider ${type.color} flex items-center gap-1`}>
                                        <Wallet size={10} /> {type.label} Accounts ({typeAccounts.length})
                                    </p>
                                    {typeAccounts.map((acc) => (
                                        <div key={acc.id} className="flex items-center gap-2 py-1.5 px-2 bg-slate-800/30 border border-slate-700 group">
                                            {editingId === acc.id ? (
                                                <>
                                                    <input
                                                        type="text"
                                                        value={editForm.name || acc.name}
                                                        onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                                                        className="flex-1 bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs"
                                                    />
                                                    {type.value === 'expense' && (
                                                        <input
                                                            type="number"
                                                            placeholder="Budget"
                                                            value={editForm.budget_limit ?? acc.budget_limit ?? ''}
                                                            onChange={(e) => setEditForm({ ...editForm, budget_limit: e.target.value ? parseFloat(e.target.value) : null })}
                                                            className="w-24 bg-slate-900 border border-slate-600 px-1 py-0.5 text-xs font-mono-nums"
                                                        />
                                                    )}
                                                    <button onClick={() => handleUpdateAccount(acc.id)} className="p-1 text-emerald-400 hover:bg-slate-700">
                                                        <Save size={12} />
                                                    </button>
                                                    <button onClick={() => setEditingId(null)} className="p-1 text-slate-400 hover:bg-slate-700">
                                                        <X size={12} />
                                                    </button>
                                                </>
                                            ) : (
                                                <>
                                                    <span className="flex-1 text-xs capitalize">{acc.name.replace(/_/g, ' ')}</span>
                                                    <span className="text-xs font-mono-nums text-slate-400">{formatCurrency(acc.balance)}</span>
                                                    {type.value === 'expense' && acc.budget_limit && (
                                                        <span className="text-[10px] text-amber-400">Budget: {formatCurrency(acc.budget_limit)}</span>
                                                    )}
                                                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                        <button
                                                            onClick={() => { setEditingId(acc.id); setEditForm({ name: acc.name, budget_limit: acc.budget_limit }); }}
                                                            className="p-1 text-slate-500 hover:text-white hover:bg-slate-700"
                                                        >
                                                            <Edit size={10} />
                                                        </button>
                                                        <button
                                                            onClick={() => handleDeleteAccount(acc.id)}
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

                        {/* Add Account Form */}
                        {showAddAccount ? (
                            <div className="border border-dashed border-emerald-700 p-3 space-y-2">
                                <div className="grid grid-cols-3 gap-2">
                                    <input
                                        type="text"
                                        placeholder="Account name"
                                        value={newAccount.name}
                                        onChange={(e) => setNewAccount({ ...newAccount, name: e.target.value })}
                                        className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                                    />
                                    <select
                                        value={newAccount.account_type}
                                        onChange={(e) => setNewAccount({ ...newAccount, account_type: e.target.value })}
                                        className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                                    >
                                        {ACCOUNT_TYPES.map((t) => (
                                            <option key={t.value} value={t.value}>{t.label}</option>
                                        ))}
                                    </select>
                                    {newAccount.account_type === 'expense' && (
                                        <input
                                            type="number"
                                            placeholder="Monthly budget"
                                            value={newAccount.budget_limit}
                                            onChange={(e) => setNewAccount({ ...newAccount, budget_limit: e.target.value })}
                                            className="bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                                        />
                                    )}
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        onClick={handleAddAccount}
                                        className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-1.5 text-xs"
                                    >
                                        Create Account
                                    </button>
                                    <button
                                        onClick={() => setShowAddAccount(false)}
                                        className="px-3 bg-slate-700 hover:bg-slate-600 text-white py-1.5 text-xs"
                                    >
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

            default:
                return null;
        }
    };

    return (
        <div className="h-full p-4 overflow-auto">
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                <div className="p-4">
                    {renderTabContent()}
                </div>
            </TabPanel>
        </div>
    );
}
