import { useState } from 'react';
import { X, ArrowRightLeft, CreditCard, Package, Sparkles, Send, Loader2 } from 'lucide-react';
import TabPanel from './TabPanel';

interface QuickInputDrawerProps {
    isOpen: boolean;
    onClose: () => void;
}

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

const TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'debt', label: 'Debt Pay' },
    { id: 'product', label: 'Product' },
    { id: 'ai', label: 'AI' },
];

export default function QuickInputDrawer({ isOpen, onClose }: QuickInputDrawerProps) {
    const [activeTab, setActiveTab] = useState('transaction');
    const [isProcessing, setIsProcessing] = useState(false);

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

    const handleAiSubmit = async () => {
        if (!aiInput.trim()) return;

        setIsProcessing(true);
        setAiResult(null);

        // Get API key from localStorage
        const apiKey = localStorage.getItem('gemini_api_key');

        if (!apiKey) {
            setAiResult('⚠️ Please set your Gemini API key in Settings first.');
            setIsProcessing(false);
            return;
        }

        try {
            // Call Gemini API to parse the natural language input
            const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{
                        parts: [{
                            text: `Parse this expense/transaction description and extract structured data. Return JSON only.
Input: "${aiInput}"

Return format:
{
  "type": "transaction" | "debt_payment" | "product",
  "amount": number,
  "currency": "JPY" | "USD" | "EUR",
  "category": string,
  "description": string,
  "from_account": string (optional),
  "to_account": string (optional),
  "product_name": string (optional),
  "location": string (optional)
}`
                        }]
                    }],
                    generationConfig: { temperature: 0.1 }
                })
            });

            const data = await response.json();
            const text = data.candidates?.[0]?.content?.parts?.[0]?.text || '';

            // Try to parse JSON from response
            const jsonMatch = text.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                const parsed = JSON.parse(jsonMatch[0]);
                setAiResult(`✅ Parsed: ${parsed.type}\n💰 Amount: ${parsed.currency} ${parsed.amount}\n📁 Category: ${parsed.category}\n📝 ${parsed.description}`);

                // Auto-fill the appropriate form
                if (parsed.type === 'transaction') {
                    setTxForm({
                        amount: String(parsed.amount),
                        category: parsed.category || '',
                        currency: parsed.currency || 'JPY',
                        fromAccount: parsed.from_account || '',
                        toAccount: parsed.to_account || 'expense',
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
                setAiResult(`📝 ${text}`);
            }
        } catch (error) {
            setAiResult(`❌ Error: ${error instanceof Error ? error.message : 'Failed to process'}`);
        } finally {
            setIsProcessing(false);
        }
    };

    if (!isOpen) return null;

    const renderTabContent = () => {
        switch (activeTab) {
            case 'transaction':
                return (
                    <div className="space-y-3">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Amount</label>
                            <div className="flex gap-2">
                                <input
                                    type="number"
                                    placeholder="0"
                                    value={txForm.amount}
                                    onChange={(e) => setTxForm({ ...txForm, amount: e.target.value })}
                                    className="flex-1 bg-slate-800 border border-slate-700 px-3 py-2 text-lg font-mono-nums focus:outline-none focus:border-emerald-500"
                                    autoFocus
                                />
                                <select
                                    value={txForm.currency}
                                    onChange={(e) => setTxForm({ ...txForm, currency: e.target.value })}
                                    className="w-20 bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                >
                                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                                </select>
                            </div>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</label>
                            <input
                                type="text"
                                placeholder="e.g., Food, Transport"
                                value={txForm.category}
                                onChange={(e) => setTxForm({ ...txForm, category: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From</label>
                                <select
                                    value={txForm.fromAccount}
                                    onChange={(e) => setTxForm({ ...txForm, fromAccount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    <option value="cash">Cash</option>
                                    <option value="bank">Bank</option>
                                    <option value="credit">Credit Card</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To</label>
                                <select
                                    value={txForm.toAccount}
                                    onChange={(e) => setTxForm({ ...txForm, toAccount: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select...</option>
                                    <option value="expense">Expense</option>
                                    <option value="savings">Savings</option>
                                    <option value="investment">Investment</option>
                                </select>
                            </div>
                        </div>
                        <button onClick={handleTransactionSubmit} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 text-sm font-medium flex items-center justify-center gap-1">
                            <ArrowRightLeft size={14} /> Save Transaction
                        </button>
                    </div>
                );

            case 'debt':
                return (
                    <div className="space-y-3">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Repayment Amount</label>
                            <div className="flex gap-2">
                                <input
                                    type="number"
                                    placeholder="0"
                                    value={debtForm.amount}
                                    onChange={(e) => setDebtForm({ ...debtForm, amount: e.target.value })}
                                    className="flex-1 bg-slate-800 border border-slate-700 px-3 py-2 text-lg font-mono-nums focus:outline-none focus:border-emerald-500"
                                />
                                <select
                                    value={debtForm.currency}
                                    onChange={(e) => setDebtForm({ ...debtForm, currency: e.target.value })}
                                    className="w-20 bg-slate-800 border border-slate-700 px-2 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                >
                                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                                </select>
                            </div>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Debt Account</label>
                            <select
                                value={debtForm.debtAccount}
                                onChange={(e) => setDebtForm({ ...debtForm, debtAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select debt...</option>
                                <option value="cc-mufg">Credit Card (MUFG)</option>
                                <option value="cc-smbc">Credit Card (SMBC)</option>
                                <option value="loan-jasso">Student Loan (JASSO)</option>
                            </select>
                        </div>
                        <button onClick={handleDebtSubmit} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 text-sm font-medium flex items-center justify-center gap-1">
                            <CreditCard size={14} /> Record Payment
                        </button>
                    </div>
                );

            case 'product':
                return (
                    <div className="space-y-3">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Product Name</label>
                            <input
                                type="text"
                                placeholder="e.g., Milk"
                                value={productForm.name}
                                onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Price</label>
                                <input
                                    type="number"
                                    placeholder="0"
                                    value={productForm.price}
                                    onChange={(e) => setProductForm({ ...productForm, price: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</label>
                                <input
                                    type="text"
                                    placeholder="Groceries"
                                    value={productForm.category}
                                    onChange={(e) => setProductForm({ ...productForm, category: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Location (Store)</label>
                            <input
                                type="text"
                                placeholder="e.g., LIFE Supermarket"
                                value={productForm.location}
                                onChange={(e) => setProductForm({ ...productForm, location: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <button onClick={handleProductSubmit} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 text-sm font-medium flex items-center justify-center gap-1">
                            <Package size={14} /> Save Product
                        </button>
                    </div>
                );

            case 'ai':
                return (
                    <div className="space-y-3">
                        <div className="border border-amber-800/50 bg-amber-900/10 p-2 text-xs">
                            <p className="flex items-center gap-1 text-amber-400">
                                <Sparkles size={12} /> Describe your expense in natural language
                            </p>
                        </div>
                        <div>
                            <textarea
                                placeholder="e.g., Spent 1500 yen on lunch at Yoshinoya today"
                                value={aiInput}
                                onChange={(e) => setAiInput(e.target.value)}
                                className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 h-24 resize-none"
                            />
                        </div>
                        {aiResult && (
                            <div className="border border-slate-700 bg-slate-800/50 p-2 text-xs whitespace-pre-wrap">
                                {aiResult}
                            </div>
                        )}
                        <button
                            onClick={handleAiSubmit}
                            disabled={isProcessing || !aiInput.trim()}
                            className="w-full bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white py-2.5 text-sm font-medium flex items-center justify-center gap-1"
                        >
                            {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                            {isProcessing ? 'Processing...' : 'Parse with AI'}
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

            <div className="fixed right-0 top-0 h-full w-80 bg-slate-900 border-l border-slate-800 z-50 flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
                    <h2 className="text-sm font-semibold">Quick Record</h2>
                    <button onClick={onClose} className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors">
                        <X size={18} />
                    </button>
                </div>

                {/* Tabs & Content */}
                <div className="flex-1 overflow-auto">
                    <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                        <div className="p-4">
                            {renderTabContent()}
                        </div>
                    </TabPanel>
                </div>
            </div>
        </>
    );
}
