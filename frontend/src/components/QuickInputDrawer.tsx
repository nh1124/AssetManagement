import { useState, useRef } from 'react';
import { X, ArrowRightLeft, CreditCard, Package, Sparkles, Loader2, ImagePlus } from 'lucide-react';
import TabPanel from './TabPanel';

interface QuickInputDrawerProps {
    isOpen: boolean;
    onClose: () => void;
}

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

const TABS = [
    { id: 'transaction', label: 'Tx' },
    { id: 'debt', label: 'Debt' },
    { id: 'product', label: 'Product' },
    { id: 'ai', label: 'AI' },
];

export default function QuickInputDrawer({ isOpen, onClose }: QuickInputDrawerProps) {
    const [activeTab, setActiveTab] = useState('transaction');
    const [isProcessing, setIsProcessing] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Transaction form
    const [txForm, setTxForm] = useState({
        amount: '',
        category: '',
        currency: 'JPY',
        fromAccount: '',
        toAccount: '',
    });

    // Debt form
    const [debtForm, setDebtForm] = useState({
        amount: '',
        debtAccount: '',
        currency: 'JPY',
    });

    // Product form
    const [productForm, setProductForm] = useState({
        name: '',
        price: '',
        location: '',
        category: '',
    });

    // AI form
    const [aiInput, setAiInput] = useState('');
    const [aiResult, setAiResult] = useState<string | null>(null);
    const [selectedImage, setSelectedImage] = useState<string | null>(null);

    const handleTransactionSubmit = () => {
        console.log('Transaction:', txForm);
        setTxForm({ amount: '', category: '', currency: 'JPY', fromAccount: '', toAccount: '' });
        onClose();
    };

    const handleDebtSubmit = () => {
        console.log('Debt Payment:', debtForm);
        setDebtForm({ amount: '', debtAccount: '', currency: 'JPY' });
        onClose();
    };

    const handleProductSubmit = () => {
        console.log('Product:', productForm);
        setProductForm({ name: '', price: '', location: '', category: '' });
        onClose();
    };

    const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onloadend = () => {
                setSelectedImage(reader.result as string);
            };
            reader.readAsDataURL(file);
        }
    };

    const handleAiSubmit = async () => {
        if (!aiInput.trim() && !selectedImage) return;

        setIsProcessing(true);
        setAiResult(null);

        const apiKey = localStorage.getItem('gemini_api_key');

        if (!apiKey) {
            setAiResult('⚠️ Set Gemini API key in Settings first.');
            setIsProcessing(false);
            return;
        }

        try {
            const parts: any[] = [{
                text: `Parse this expense/transaction and extract structured data. Return JSON only.
${aiInput ? `Text: "${aiInput}"` : 'Analyze the receipt/image.'}

Return format:
{"type": "transaction" | "debt_payment" | "product", "amount": number, "currency": "JPY" | "USD" | "EUR", "category": string, "description": string, "product_name": string (optional), "location": string (optional)}`
            }];

            if (selectedImage) {
                const base64Data = selectedImage.split(',')[1];
                const mimeType = selectedImage.split(';')[0].split(':')[1];
                parts.push({
                    inline_data: { mime_type: mimeType, data: base64Data }
                });
            }

            const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{ parts }],
                    generationConfig: { temperature: 0.1 }
                })
            });

            const data = await response.json();
            const text = data.candidates?.[0]?.content?.parts?.[0]?.text || '';

            const jsonMatch = text.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                const parsed = JSON.parse(jsonMatch[0]);
                setAiResult(`✅ ${parsed.type}\n💰 ${parsed.currency} ${parsed.amount}\n📁 ${parsed.category}`);

                if (parsed.type === 'transaction') {
                    setTxForm({
                        amount: String(parsed.amount),
                        category: parsed.category || '',
                        currency: parsed.currency || 'JPY',
                        fromAccount: '',
                        toAccount: 'expense',
                    });
                    setActiveTab('transaction');
                } else if (parsed.type === 'product') {
                    setProductForm({
                        name: parsed.product_name || parsed.description,
                        price: String(parsed.amount),
                        location: parsed.location || '',
                        category: parsed.category || '',
                    });
                    setActiveTab('product');
                }
            } else {
                setAiResult(`📝 ${text.substring(0, 100)}`);
            }
        } catch (error) {
            setAiResult(`❌ ${error instanceof Error ? error.message : 'Failed'}`);
        } finally {
            setIsProcessing(false);
        }
    };

    if (!isOpen) return null;

    const renderTabContent = () => {
        switch (activeTab) {
            case 'transaction':
                return (
                    <div className="space-y-2">
                        <div className="flex gap-1">
                            <input
                                type="number"
                                placeholder="0"
                                value={txForm.amount}
                                onChange={(e) => setTxForm({ ...txForm, amount: e.target.value })}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-base font-mono-nums focus:outline-none focus:border-emerald-500"
                                autoFocus
                            />
                            <select
                                value={txForm.currency}
                                onChange={(e) => setTxForm({ ...txForm, currency: e.target.value })}
                                className="w-16 bg-slate-800 border border-slate-700 px-1 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                            </select>
                        </div>
                        <input
                            type="text"
                            placeholder="Category"
                            value={txForm.category}
                            onChange={(e) => setTxForm({ ...txForm, category: e.target.value })}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                        <div className="flex gap-1">
                            <select
                                value={txForm.fromAccount}
                                onChange={(e) => setTxForm({ ...txForm, fromAccount: e.target.value })}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">From...</option>
                                <option value="cash">Cash</option>
                                <option value="bank">Bank</option>
                                <option value="credit">Credit</option>
                            </select>
                            <select
                                value={txForm.toAccount}
                                onChange={(e) => setTxForm({ ...txForm, toAccount: e.target.value })}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">To...</option>
                                <option value="expense">Expense</option>
                                <option value="savings">Savings</option>
                                <option value="invest">Invest</option>
                            </select>
                        </div>
                        <button onClick={handleTransactionSubmit} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 text-xs font-medium flex items-center justify-center gap-1">
                            <ArrowRightLeft size={12} /> Save
                        </button>
                    </div>
                );

            case 'debt':
                return (
                    <div className="space-y-2">
                        <div className="flex gap-1">
                            <input
                                type="number"
                                placeholder="0"
                                value={debtForm.amount}
                                onChange={(e) => setDebtForm({ ...debtForm, amount: e.target.value })}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-base font-mono-nums focus:outline-none focus:border-emerald-500"
                            />
                            <select
                                value={debtForm.currency}
                                onChange={(e) => setDebtForm({ ...debtForm, currency: e.target.value })}
                                className="w-16 bg-slate-800 border border-slate-700 px-1 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                            </select>
                        </div>
                        <select
                            value={debtForm.debtAccount}
                            onChange={(e) => setDebtForm({ ...debtForm, debtAccount: e.target.value })}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        >
                            <option value="">Select debt...</option>
                            <option value="cc-mufg">CC (MUFG)</option>
                            <option value="cc-smbc">CC (SMBC)</option>
                            <option value="loan">Loan</option>
                        </select>
                        <button onClick={handleDebtSubmit} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 text-xs font-medium flex items-center justify-center gap-1">
                            <CreditCard size={12} /> Pay
                        </button>
                    </div>
                );

            case 'product':
                return (
                    <div className="space-y-2">
                        <input
                            type="text"
                            placeholder="Product name"
                            value={productForm.name}
                            onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                        <div className="flex gap-1">
                            <input
                                type="number"
                                placeholder="Price"
                                value={productForm.price}
                                onChange={(e) => setProductForm({ ...productForm, price: e.target.value })}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                            />
                            <input
                                type="text"
                                placeholder="Category"
                                value={productForm.category}
                                onChange={(e) => setProductForm({ ...productForm, category: e.target.value })}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <input
                            type="text"
                            placeholder="Location (store)"
                            value={productForm.location}
                            onChange={(e) => setProductForm({ ...productForm, location: e.target.value })}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                        <button onClick={handleProductSubmit} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 text-xs font-medium flex items-center justify-center gap-1">
                            <Package size={12} /> Save
                        </button>
                    </div>
                );

            case 'ai':
                return (
                    <div className="space-y-2">
                        <div className="flex gap-1">
                            <textarea
                                placeholder="Describe expense or upload receipt..."
                                value={aiInput}
                                onChange={(e) => setAiInput(e.target.value)}
                                className="flex-1 min-w-0 bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500 h-16 resize-none"
                            />
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                className="w-10 h-16 bg-slate-800 border border-slate-700 hover:border-amber-500 flex items-center justify-center text-slate-400 hover:text-amber-400"
                            >
                                <ImagePlus size={16} />
                            </button>
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept="image/*"
                                onChange={handleImageSelect}
                                className="hidden"
                            />
                        </div>
                        {selectedImage && (
                            <div className="relative">
                                <img src={selectedImage} alt="Receipt" className="w-full h-20 object-cover border border-slate-700" />
                                <button
                                    onClick={() => setSelectedImage(null)}
                                    className="absolute top-1 right-1 bg-slate-900/80 p-0.5 text-slate-400 hover:text-white"
                                >
                                    <X size={12} />
                                </button>
                            </div>
                        )}
                        {aiResult && (
                            <div className="border border-slate-700 bg-slate-800/50 p-2 text-[10px] whitespace-pre-wrap">
                                {aiResult}
                            </div>
                        )}
                        <button
                            onClick={handleAiSubmit}
                            disabled={isProcessing || (!aiInput.trim() && !selectedImage)}
                            className="w-full bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white py-2 text-xs font-medium flex items-center justify-center gap-1"
                        >
                            {isProcessing ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                            {isProcessing ? 'Processing...' : 'Parse'}
                        </button>
                    </div>
                );

            default:
                return null;
        }
    };

    return (
        <>
            <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

            <div className="fixed right-0 top-0 h-full w-72 bg-slate-900 border-l border-slate-800 z-50 flex flex-col shadow-2xl overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 flex-shrink-0">
                    <h2 className="text-xs font-semibold">Quick Record</h2>
                    <button onClick={onClose} className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors">
                        <X size={16} />
                    </button>
                </div>

                {/* Tabs & Content */}
                <div className="flex-1 overflow-y-auto overflow-x-hidden">
                    <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                        <div className="p-3">
                            {renderTabContent()}
                        </div>
                    </TabPanel>
                </div>
            </div>
        </>
    );
}
