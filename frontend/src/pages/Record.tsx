import { useState, useEffect, useRef } from 'react';
import { Plus, ArrowUpCircle, ArrowDownCircle, RefreshCw, Edit, Trash2, CreditCard, Package, Sparkles, Send, Loader2, ImagePlus, X } from 'lucide-react';
import SplitView from '../components/SplitView';
import TabPanel from '../components/TabPanel';
import type { Transaction } from '../types';
import { getTransactions, createTransaction } from '../api';

const CURRENCIES = ['JPY', 'USD', 'EUR', 'GBP', 'CNY'];

const INPUT_TABS = [
    { id: 'transaction', label: 'Transaction' },
    { id: 'ai', label: 'AI' },
];

export default function RecordPage() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [activeTab, setActiveTab] = useState('transaction');
    const [isProcessing, setIsProcessing] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        description: '',
        amount: '',
        type: 'Expense' as 'Income' | 'Expense' | 'Transfer' | 'Debt',
        category: '',
        currency: 'JPY',
        fromAccount: '',
        toAccount: '',
    });

    // AI state
    const [aiInput, setAiInput] = useState('');
    const [aiResult, setAiResult] = useState<string | null>(null);
    const [selectedImage, setSelectedImage] = useState<string | null>(null);

    useEffect(() => {
        getTransactions().then(setTransactions).catch(console.error);
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const newTransaction = await createTransaction({
                date: formData.date,
                description: formData.description,
                amount: parseFloat(formData.amount),
                type: formData.type,
                category: formData.category,
                currency: formData.currency,
                from_account: formData.fromAccount,
                to_account: formData.toAccount,
            });
            setTransactions([newTransaction, ...transactions]);
            setFormData({ ...formData, description: '', amount: '', category: '' });
        } catch (error) {
            console.error('Failed to create transaction:', error);
        }
    };

    const getCurrencySymbol = (currency: string) => {
        const symbols: Record<string, string> = { JPY: '¥', USD: '$', EUR: '€', GBP: '£', CNY: '¥' };
        return symbols[currency] || currency;
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
            setAiResult('⚠️ Please set your Gemini API key in Settings first.');
            setIsProcessing(false);
            return;
        }

        try {
            const parts: any[] = [{
                text: `Analyze this expense/transaction and extract structured data. If there's an image, analyze the receipt/document. Return JSON only.
${aiInput ? `Text input: "${aiInput}"` : 'Analyze the uploaded receipt/image.'}

Return format (JSON only, no markdown):
{
  "type": "transaction" | "debt_payment" | "product",
  "amount": number,
  "currency": "JPY" | "USD" | "EUR",
  "category": string,
  "description": string,
  "date": "YYYY-MM-DD" (optional),
  "product_name": string (optional, for product type),
  "location": string (optional),
  "items": [{"name": string, "price": number}] (optional, for receipts with multiple items)
}`
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

                let resultText = `✅ Type: ${parsed.type}\n💰 Amount: ${parsed.currency} ${parsed.amount}\n📁 Category: ${parsed.category}\n📝 ${parsed.description}`;

                if (parsed.items && parsed.items.length > 0) {
                    resultText += '\n\n📋 Items:';
                    parsed.items.forEach((item: any) => {
                        resultText += `\n  • ${item.name}: ¥${item.price}`;
                    });
                }

                setAiResult(resultText);

                // Auto-fill the transaction form
                if (parsed.type === 'transaction' || parsed.type === 'product') {
                    setFormData({
                        ...formData,
                        amount: String(parsed.amount),
                        category: parsed.category || '',
                        currency: parsed.currency || 'JPY',
                        description: parsed.description || '',
                        date: parsed.date || formData.date,
                    });
                    setActiveTab('transaction');
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

    const leftPane = (
        <TabPanel tabs={INPUT_TABS} activeTab={activeTab} onTabChange={setActiveTab}>
            {activeTab === 'transaction' && (
                <form onSubmit={handleSubmit} className="space-y-3">
                    <div className="grid grid-cols-2 gap-2">
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
                                onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="Expense">Expense</option>
                                <option value="Income">Income</option>
                                <option value="Transfer">Transfer</option>
                                <option value="Debt">Debt Repayment</option>
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

                    <div className="grid grid-cols-2 gap-2">
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

                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">From Account</label>
                            <select
                                value={formData.fromAccount}
                                onChange={(e) => setFormData({ ...formData, fromAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select...</option>
                                <option value="cash">Cash</option>
                                <option value="bank">Bank Account</option>
                                <option value="credit">Credit Card</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">To Account</label>
                            <select
                                value={formData.toAccount}
                                onChange={(e) => setFormData({ ...formData, toAccount: e.target.value })}
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">Select...</option>
                                <option value="expense">Expense</option>
                                <option value="savings">Savings</option>
                                <option value="investment">Investment</option>
                            </select>
                        </div>
                    </div>

                    <button
                        type="submit"
                        className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                    >
                        <Plus size={14} /> Save Transaction
                    </button>
                </form>
            )}

            {activeTab === 'debt' && (
                <form className="space-y-3">
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date</label>
                        <input
                            type="date"
                            defaultValue={new Date().toISOString().split('T')[0]}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                    </div>
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Debt Account</label>
                        <select className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500">
                            <option value="">Select debt...</option>
                            <option value="cc-mufg">Credit Card (MUFG)</option>
                            <option value="loan">Student Loan</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Repayment Amount</label>
                        <input
                            type="number"
                            placeholder="0"
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                        />
                    </div>
                    <button className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors">
                        <CreditCard size={14} /> Record Repayment
                    </button>
                </form>
            )}

            {activeTab === 'product' && (
                <form className="space-y-3">
                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Product Name</label>
                        <input
                            type="text"
                            placeholder="e.g., Milk"
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Price</label>
                            <input
                                type="number"
                                placeholder="0"
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Location</label>
                            <input
                                type="text"
                                placeholder="Store name"
                                className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500"
                            />
                        </div>
                    </div>
                    <button className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors">
                        <Package size={14} /> Save Product
                    </button>
                </form>
            )}

            {activeTab === 'ai' && (
                <div className="space-y-3">
                    <div className="border border-amber-800/50 bg-amber-900/10 p-2 text-xs">
                        <p className="flex items-center gap-1 text-amber-400">
                            <Sparkles size={12} /> Describe expense or upload receipt image
                        </p>
                    </div>

                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description or instruction</label>
                        <textarea
                            placeholder="e.g., Spent 1500 yen on lunch at Yoshinoya today"
                            value={aiInput}
                            onChange={(e) => setAiInput(e.target.value)}
                            className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs focus:outline-none focus:border-emerald-500 h-20 resize-none"
                        />
                    </div>

                    <div>
                        <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1">Receipt / Document Image</label>
                        <div className="flex gap-2">
                            <button
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                className="flex-1 bg-slate-800 border border-dashed border-slate-600 hover:border-amber-500 py-3 flex items-center justify-center gap-1 text-xs text-slate-400 hover:text-amber-400"
                            >
                                <ImagePlus size={16} /> {selectedImage ? 'Change Image' : 'Upload Image'}
                            </button>
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept="image/*"
                                onChange={handleImageSelect}
                                className="hidden"
                            />
                        </div>
                    </div>

                    {selectedImage && (
                        <div className="relative">
                            <img src={selectedImage} alt="Receipt" className="w-full h-32 object-cover border border-slate-700" />
                            <button
                                onClick={() => setSelectedImage(null)}
                                className="absolute top-1 right-1 bg-slate-900/80 p-1 text-slate-400 hover:text-white"
                            >
                                <X size={14} />
                            </button>
                        </div>
                    )}

                    {aiResult && (
                        <div className="border border-slate-700 bg-slate-800/50 p-3 text-xs whitespace-pre-wrap max-h-40 overflow-auto">
                            {aiResult}
                        </div>
                    )}

                    <button
                        onClick={handleAiSubmit}
                        disabled={isProcessing || (!aiInput.trim() && !selectedImage)}
                        className="w-full bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white py-2 flex items-center justify-center gap-1 text-xs font-medium transition-colors"
                    >
                        {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        {isProcessing ? 'Processing with AI...' : 'Parse with Gemini'}
                    </button>
                </div>
            )}
        </TabPanel>
    );

    const rightPane = (
        <div className="space-y-3">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Recent Transactions</h3>
            <div className="space-y-0.5 max-h-[calc(100vh-180px)] overflow-auto">
                {transactions.length === 0 ? (
                    <p className="text-slate-600 text-xs py-8 text-center">No transactions yet</p>
                ) : (
                    transactions.map((tx) => (
                        <div
                            key={tx.id}
                            className="flex items-center justify-between py-2 px-2 hover:bg-slate-800/50 transition-colors border-l-2 border-transparent hover:border-slate-600 group"
                        >
                            <div className="flex items-center gap-2">
                                {tx.type === 'Income' ? (
                                    <ArrowUpCircle className="text-emerald-500" size={14} />
                                ) : tx.type === 'Expense' ? (
                                    <ArrowDownCircle className="text-rose-500" size={14} />
                                ) : (
                                    <RefreshCw className="text-cyan-500" size={14} />
                                )}
                                <div>
                                    <p className="text-xs">{tx.description}</p>
                                    <p className="text-[10px] text-slate-600">{tx.date} • {tx.category || 'Uncategorized'}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={`text-xs font-mono-nums ${tx.type === 'Income' ? 'text-emerald-500' : tx.type === 'Expense' ? 'text-rose-500' : 'text-cyan-500'}`}>
                                    {tx.type === 'Income' ? '+' : tx.type === 'Expense' ? '-' : ''}{getCurrencySymbol(tx.currency || 'JPY')}{tx.amount.toLocaleString()}
                                </span>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-slate-300">
                                        <Edit size={12} />
                                    </button>
                                    <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-rose-400">
                                        <Trash2 size={12} />
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );

    return <SplitView left={leftPane} right={rightPane} leftTitle="Input & Record" rightTitle="Maintenance" />;
}
