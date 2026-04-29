import { useEffect, useMemo, useState } from 'react';
import { Package, RefreshCw, Plus, Pencil, Trash2, X } from 'lucide-react';
import type { Product } from '../types';
import { getProducts, getUnitEconomicsSummary, createProduct, updateProduct, deleteProduct } from '../api';

// ── 定数 ──────────────────────────────────────────────────────────────────────

const CATEGORIES = ['家電', '家具', '消耗品', '衣類・寝具', '日用品', '食器・調理器具', 'その他'];
const LOCATIONS   = ['メインルーム', 'キッチン', '洗面所', 'トイレ', '玄関', 'クローゼット'];

const EMPTY_FORM = {
    name: '',
    category: '家電',
    location: 'メインルーム',
    is_asset: true,
    purchase_price: '',
    purchase_date: '',
    lifespan_months: '',
    last_unit_price: '',
    units_per_purchase: '1',
    frequency_days: '',
    last_purchase_date: '',
};

type FormState = typeof EMPTY_FORM;

// ── ヘルパー ──────────────────────────────────────────────────────────────────

function toPayload(f: FormState) {
    return {
        name:               f.name,
        category:           f.category,
        location:           f.location || null,
        is_asset:           f.is_asset,
        // 耐久財フィールド
        purchase_price:     f.purchase_price     ? parseFloat(f.purchase_price)     : null,
        purchase_date:      f.purchase_date      || null,
        lifespan_months:    f.lifespan_months    ? parseInt(f.lifespan_months)       : null,
        // 消耗品フィールド
        last_unit_price:    f.last_unit_price    ? parseFloat(f.last_unit_price)     : 0,
        units_per_purchase: f.units_per_purchase ? parseInt(f.units_per_purchase)    : 1,
        frequency_days:     f.frequency_days     ? parseInt(f.frequency_days)        : 0,
        last_purchase_date: f.last_purchase_date || null,
    };
}

function productToForm(p: any): FormState {
    return {
        name:               p.name ?? '',
        category:           p.category ?? '家電',
        location:           p.location ?? 'メインルーム',
        is_asset:           p.is_asset ?? true,
        purchase_price:     p.purchase_price    != null ? String(p.purchase_price)    : '',
        purchase_date:      p.purchase_date     ?? '',
        lifespan_months:    p.lifespan_months   != null ? String(p.lifespan_months)   : '',
        last_unit_price:    p.last_unit_price   != null ? String(p.last_unit_price)   : '',
        units_per_purchase: p.units_per_purchase != null ? String(p.units_per_purchase) : '1',
        frequency_days:     p.frequency_days    != null ? String(p.frequency_days)    : '',
        last_purchase_date: p.last_purchase_date ?? '',
    };
}

// ── モーダル ──────────────────────────────────────────────────────────────────

interface ModalProps {
    editTarget: any | null;
    onClose: () => void;
    onSaved: () => void;
}

function ProductModal({ editTarget, onClose, onSaved }: ModalProps) {
    const [form, setForm] = useState<FormState>(
        editTarget ? productToForm(editTarget) : EMPTY_FORM
    );
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [error, setError] = useState('');

    const set = (key: keyof FormState, value: any) =>
        setForm((prev) => ({ ...prev, [key]: value }));

    const handleSave = async () => {
        if (!form.name.trim()) { setError('物品名を入力してください'); return; }
        setSaving(true);
        setError('');
        try {
            const payload = toPayload(form);
            if (editTarget) {
                await updateProduct(editTarget.id, payload);
            } else {
                await createProduct(payload);
            }
            onSaved();
            onClose();
        } catch (e: any) {
            setError(e?.response?.data?.detail ?? '保存に失敗しました');
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!editTarget || !confirm(`「${editTarget.name}」を削除しますか？`)) return;
        setDeleting(true);
        try {
            await deleteProduct(editTarget.id);
            onSaved();
            onClose();
        } catch {
            setError('削除に失敗しました');
        } finally {
            setDeleting(false);
        }
    };

    const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
        <div className="flex flex-col gap-1">
            <label className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</label>
            {children}
        </div>
    );

    const inputCls = "bg-slate-900 border border-slate-700 text-slate-200 text-xs px-2 py-1.5 w-full focus:outline-none focus:border-slate-500";
    const selectCls = inputCls;

    return (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
            <div className="bg-slate-950 border border-slate-700 w-full max-w-lg max-h-[90vh] overflow-y-auto">
                {/* ヘッダー */}
                <div className="flex items-center justify-between p-4 border-b border-slate-800">
                    <h2 className="text-sm font-semibold text-slate-200">
                        {editTarget ? '物品を編集' : '物品を追加'}
                    </h2>
                    <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
                        <X size={16} />
                    </button>
                </div>

                {/* フォーム */}
                <div className="p-4 flex flex-col gap-3">

                    {/* 基本情報 */}
                    <div className="grid grid-cols-2 gap-3">
                        <div className="col-span-2">
                            <Field label="物品名 *">
                                <input
                                    className={inputCls}
                                    value={form.name}
                                    onChange={(e) => set('name', e.target.value)}
                                    placeholder="例：冷蔵庫"
                                    autoFocus
                                />
                            </Field>
                        </div>
                        <Field label="区分">
                            <select className={selectCls} value={form.category}
                                onChange={(e) => set('category', e.target.value)}>
                                {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                            </select>
                        </Field>
                        <Field label="配置箇所">
                            <select className={selectCls} value={form.location}
                                onChange={(e) => set('location', e.target.value)}>
                                {LOCATIONS.map((l) => <option key={l}>{l}</option>)}
                            </select>
                        </Field>
                    </div>

                    {/* 種別切り替え */}
                    <div className="flex gap-2">
                        {[true, false].map((isAsset) => (
                            <button
                                key={String(isAsset)}
                                onClick={() => set('is_asset', isAsset)}
                                className={`flex-1 py-1.5 text-xs border transition-colors ${
                                    form.is_asset === isAsset
                                        ? 'border-emerald-500 text-emerald-400 bg-emerald-950/40'
                                        : 'border-slate-700 text-slate-500 hover:border-slate-500'
                                }`}
                            >
                                {isAsset ? '耐久財（家電・家具）' : '消耗品'}
                            </button>
                        ))}
                    </div>

                    {/* 耐久財フィールド */}
                    {form.is_asset ? (
                        <div className="grid grid-cols-2 gap-3 border border-slate-800 p-3">
                            <p className="col-span-2 text-[10px] text-slate-600 uppercase tracking-wider">耐久財</p>
                            <Field label="購入金額（円）">
                                <input className={inputCls} type="number" min="0" step="100"
                                    value={form.purchase_price}
                                    onChange={(e) => set('purchase_price', e.target.value)}
                                    placeholder="55000" />
                            </Field>
                            <Field label="購入日">
                                <input className={inputCls} type="date"
                                    value={form.purchase_date}
                                    onChange={(e) => set('purchase_date', e.target.value)} />
                            </Field>
                            <Field label="耐用年数（月）">
                                <input className={inputCls} type="number" min="0"
                                    value={form.lifespan_months}
                                    onChange={(e) => set('lifespan_months', e.target.value)}
                                    placeholder="120（10年）" />
                            </Field>
                            <Field label="参考単価（円）">
                                <input className={inputCls} type="number" min="0" step="100"
                                    value={form.last_unit_price}
                                    onChange={(e) => set('last_unit_price', e.target.value)}
                                    placeholder="purchase_price と同値でOK" />
                            </Field>
                        </div>
                    ) : (
                        /* 消耗品フィールド */
                        <div className="grid grid-cols-2 gap-3 border border-slate-800 p-3">
                            <p className="col-span-2 text-[10px] text-slate-600 uppercase tracking-wider">消耗品</p>
                            <Field label="購入金額（円）">
                                <input className={inputCls} type="number" min="0" step="10"
                                    value={form.last_unit_price}
                                    onChange={(e) => set('last_unit_price', e.target.value)}
                                    placeholder="900" />
                            </Field>
                            <Field label="使用回数 / 購入1個">
                                <input className={inputCls} type="number" min="1"
                                    value={form.units_per_purchase}
                                    onChange={(e) => set('units_per_purchase', e.target.value)}
                                    placeholder="1" />
                            </Field>
                            <Field label="更新サイクル（日）">
                                <input className={inputCls} type="number" min="0"
                                    value={form.frequency_days}
                                    onChange={(e) => set('frequency_days', e.target.value)}
                                    placeholder="60（2ヶ月）" />
                            </Field>
                            <Field label="最終購入日">
                                <input className={inputCls} type="date"
                                    value={form.last_purchase_date}
                                    onChange={(e) => set('last_purchase_date', e.target.value)} />
                            </Field>
                        </div>
                    )}

                    {error && <p className="text-xs text-red-400">{error}</p>}
                </div>

                {/* フッター */}
                <div className="flex items-center justify-between p-4 border-t border-slate-800">
                    <div>
                        {editTarget && (
                            <button
                                onClick={handleDelete}
                                disabled={deleting}
                                className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 border border-red-900 px-3 py-1.5 hover:bg-red-950/30"
                            >
                                <Trash2 size={12} />
                                {deleting ? '削除中...' : '削除'}
                            </button>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={onClose}
                            className="text-xs text-slate-400 border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
                        >
                            キャンセル
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="text-xs text-slate-900 bg-slate-200 px-4 py-1.5 font-semibold hover:bg-white disabled:opacity-50"
                        >
                            {saving ? '保存中...' : (editTarget ? '更新' : '追加')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── メインページ ──────────────────────────────────────────────────────────────

export default function Products() {
    const [products, setProducts] = useState<Product[]>([]);
    const [summary, setSummary] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [modalOpen, setModalOpen] = useState(false);
    const [editTarget, setEditTarget] = useState<any | null>(null);

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

    useEffect(() => { fetchData(); }, []);

    const consumables = useMemo(() => products.filter((p) => !p.is_asset), [products]);
    const assets      = useMemo(() => products.filter((p) =>  p.is_asset), [products]);

    const openAdd  = () => { setEditTarget(null); setModalOpen(true); };
    const openEdit = (p: any) => { setEditTarget(p); setModalOpen(true); };

    return (
        <div className="h-full flex flex-col p-4 gap-4">
            {/* ヘッダー */}
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-lg font-semibold">Product Inventory</h1>
                    <p className="text-xs text-slate-500">Unit economics and replenishment tracking</p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={openAdd}
                        className="flex items-center gap-1 px-3 py-1.5 border border-slate-600 hover:bg-slate-800 text-slate-300 text-xs"
                    >
                        <Plus size={12} /> 追加
                    </button>
                    <button
                        onClick={fetchData}
                        className="p-2 border border-slate-700 hover:bg-slate-800 text-slate-400"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* サマリーカード */}
            <div className="grid grid-cols-3 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Total Products</p>
                    <p className="text-xl font-bold font-mono-nums text-slate-200">{products.length}</p>
                </div>
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Monthly Consumable Cost</p>
                    <p className="text-xl font-bold font-mono-nums text-amber-400">
                        ¥{Math.round(summary?.total_monthly_cost ?? 0).toLocaleString()}
                    </p>
                </div>
                <div className="p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Asset / Consumable</p>
                    <p className="text-xl font-bold font-mono-nums text-emerald-400">
                        {assets.length} / <span className="text-cyan-400">{consumables.length}</span>
                    </p>
                </div>
            </div>

            {/* テーブル */}
            <div className="border border-slate-800 flex-1 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900 sticky top-0">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">物品名</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">区分</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">配置</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">購入金額</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">月次コスト</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">次回購入</th>
                            <th className="p-2"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td className="p-3 text-slate-500" colSpan={7}>Loading...</td></tr>
                        ) : products.length === 0 ? (
                            <tr>
                                <td className="p-6 text-slate-500 text-center" colSpan={7}>
                                    物品がありません。「追加」から登録してください。
                                </td>
                            </tr>
                        ) : (
                            products.map((p: any) => (
                                <tr key={p.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 group">
                                    <td className="p-2 flex items-center gap-2">
                                        <Package size={12} className={p.is_asset ? 'text-emerald-400' : 'text-cyan-400'} />
                                        <span className="text-slate-200">{p.name}</span>
                                    </td>
                                    <td className="p-2 text-slate-400">{p.category}</td>
                                    <td className="p-2 text-slate-500">{p.location ?? '—'}</td>
                                    <td className="p-2 text-right font-mono-nums text-slate-300">
                                        ¥{(p.purchase_price ?? p.last_unit_price ?? 0).toLocaleString()}
                                    </td>
                                    <td className="p-2 text-right font-mono-nums text-cyan-400">
                                        {p.is_asset ? '—' : `¥${Math.round(p.monthly_cost).toLocaleString()}`}
                                    </td>
                                    <td className="p-2 text-slate-500">{p.next_purchase_date ?? '—'}</td>
                                    <td className="p-2 text-right">
                                        <button
                                            onClick={() => openEdit(p)}
                                            className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-slate-300 p-1"
                                        >
                                            <Pencil size={11} />
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {/* カテゴリ内訳 */}
            <div className="border border-slate-800 p-3">
                <p className="text-[10px] text-slate-500 uppercase mb-2">Top Categories (Consumables)</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {(summary?.category_breakdown ?? []).slice(0, 3).map((row: any) => (
                        <div key={row.category} className="bg-slate-900/60 border border-slate-700 p-2">
                            <p className="text-xs text-slate-300">{row.category}</p>
                            <p className="text-sm font-mono-nums text-amber-400">
                                ¥{Math.round(row.monthly_cost).toLocaleString()} / mo
                            </p>
                        </div>
                    ))}
                    {!summary?.category_breakdown?.length && (
                        <p className="text-xs text-slate-500">消耗品を追加するとここに表示されます。</p>
                    )}
                </div>
            </div>

            {/* モーダル */}
            {modalOpen && (
                <ProductModal
                    editTarget={editTarget}
                    onClose={() => setModalOpen(false)}
                    onSaved={fetchData}
                />
            )}
        </div>
    );
}
