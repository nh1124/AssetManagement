import { Coffee, Cross, Gift, Home, Info, Shirt, Smile, Sofa, Utensils, Zap } from 'lucide-react';
import type { ComponentType } from 'react';
import type { QuickTemplate, Transaction } from '../../types';

export type LanguageCode = 'ja' | 'en';

export type AccountItem = {
    id: number;
    name: string;
    account_type: string;
    balance?: number;
};

export type QuickTemplateKind =
    | 'simple_expense'
    | 'credit_expense'
    | 'expense_with_advance'
    | 'reimbursement'
    | 'transfer'
    | 'debt_payment';

export type QuickTemplateDraft = {
    tray: string;
    name: string;
    template_kind: QuickTemplateKind;
    category: string;
    default_currency: string;
    default_from_account_id: string;
    default_to_account_id: string;
    receivable_account_id: string;
    reimbursement_account_id: string;
};

export type QuickEntry = {
    date: string;
    description: string;
    amount: string;
    ownAmount: string;
    advanceAmount: string;
    currency: string;
    payment_account_id: string;
    expense_account_id: string;
    receivable_account_id: string;
    reimbursement_account_id: string;
    reimbursementReceived: boolean;
};

export type QuickPreset = {
    key: string;
    tray: string;
    name: string;
    template_kind: QuickTemplateKind;
    category: string;
    icon: ComponentType<{ size?: number; className?: string }>;
    color: string;
    accountHints: string[];
    description: Record<LanguageCode, string>;
};

export const QUICK_TEMPLATE_KINDS: Array<{
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

export const QUICK_KIND_RULES = Object.fromEntries(
    QUICK_TEMPLATE_KINDS.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<QuickTemplateKind, { fromTypes: string[]; toTypes: string[] }>;

export const quickKindLabel = (kind: string) =>
    QUICK_TEMPLATE_KINDS.find((option) => option.value === kind)?.label ?? kind;

export const QUICK_PRESETS: QuickPreset[] = [
    {
        key: 'food',
        tray: 'Food',
        name: '食費',
        template_kind: 'simple_expense',
        category: 'food',
        icon: Utensils,
        color: 'text-sky-400',
        accountHints: ['food', '食費'],
        description: {
            ja: '自炊やスーパーなど、通常の食費を記録します。',
            en: 'Records regular food spending such as groceries and home meals.',
        },
    },
    {
        key: 'treats',
        tray: 'Food',
        name: '嗜好品',
        template_kind: 'simple_expense',
        category: 'treats',
        icon: Coffee,
        color: 'text-rose-400',
        accountHints: ['entertainment', 'food', '嗜好品'],
        description: {
            ja: 'カフェ、酒、菓子など生活必需ではない飲食を記録します。',
            en: 'Records treats such as cafes, alcohol, snacks, and non-essential food.',
        },
    },
    {
        key: 'dining',
        tray: 'Food',
        name: '外食費',
        template_kind: 'expense_with_advance',
        category: 'dining',
        icon: Coffee,
        color: 'text-orange-400',
        accountHints: ['food', 'entertainment', '外食'],
        description: {
            ja: '外食を記録します。割り勘や立替がある場合は立替分も同時に展開できます。',
            en: 'Records dining out, including split bills and advances when needed.',
        },
    },
    {
        key: 'housing',
        tray: 'Living',
        name: '住居',
        template_kind: 'simple_expense',
        category: 'housing',
        icon: Home,
        color: 'text-rose-400',
        accountHints: ['utilities', 'expense', 'rent', '住居'],
        description: {
            ja: '家賃、管理費、住宅関連の支出を記録します。',
            en: 'Records rent, maintenance fees, and housing-related spending.',
        },
    },
    {
        key: 'furniture',
        tray: 'Living',
        name: '家具・家電',
        template_kind: 'simple_expense',
        category: 'furniture',
        icon: Sofa,
        color: 'text-emerald-400',
        accountHints: ['shopping', 'expense', '家具', '家電'],
        description: {
            ja: '家具、家電、生活設備の購入を記録します。',
            en: 'Records furniture, appliances, and household equipment purchases.',
        },
    },
    {
        key: 'daily',
        tray: 'Living',
        name: '日用雑貨',
        template_kind: 'simple_expense',
        category: 'daily goods',
        icon: Gift,
        color: 'text-amber-400',
        accountHints: ['shopping', 'expense', '日用'],
        description: {
            ja: '洗剤、紙類、小物などの日用品を記録します。',
            en: 'Records daily goods such as detergent, paper items, and small supplies.',
        },
    },
    {
        key: 'utilities',
        tray: 'Bills',
        name: '光熱費',
        template_kind: 'simple_expense',
        category: 'utilities',
        icon: Zap,
        color: 'text-amber-400',
        accountHints: ['utilities', '光熱'],
        description: {
            ja: '電気、ガス、水道、通信などの固定的な生活費を記録します。',
            en: 'Records utilities such as electricity, gas, water, and connectivity.',
        },
    },
    {
        key: 'clothing',
        tray: 'Personal',
        name: '衣服',
        template_kind: 'simple_expense',
        category: 'clothing',
        icon: Shirt,
        color: 'text-slate-300',
        accountHints: ['shopping', '衣服'],
        description: {
            ja: '衣服、靴、バッグなど身につけるものを記録します。',
            en: 'Records clothing, shoes, bags, and wearable items.',
        },
    },
    {
        key: 'medical',
        tray: 'Personal',
        name: '医療',
        template_kind: 'simple_expense',
        category: 'medical',
        icon: Cross,
        color: 'text-teal-400',
        accountHints: ['expense', 'medical', '医療'],
        description: {
            ja: '病院、薬、検査など医療関連の支出を記録します。',
            en: 'Records medical expenses such as clinics, medicine, and tests.',
        },
    },
    {
        key: 'beauty',
        tray: 'Personal',
        name: '美容・衛生',
        template_kind: 'simple_expense',
        category: 'beauty hygiene',
        icon: Smile,
        color: 'text-violet-400',
        accountHints: ['shopping', 'expense', '美容', '衛生'],
        description: {
            ja: '美容院、化粧品、衛生用品などを記録します。',
            en: 'Records salons, cosmetics, hygiene goods, and self-care spending.',
        },
    },
];

export const quickText = (language: LanguageCode) => ({
    quickTemplates: language === 'ja' ? 'クイックテンプレート' : 'Quick Templates',
    newTemplate: language === 'ja' ? 'テンプレート作成' : 'Create Template',
    tray: language === 'ja' ? 'トレイ' : 'Tray',
    templateName: language === 'ja' ? 'テンプレート名' : 'Template Name',
    kind: language === 'ja' ? '種類' : 'Kind',
    currency: language === 'ja' ? '通貨' : 'Currency',
    from: language === 'ja' ? '支払元' : 'From',
    to: language === 'ja' ? '相手勘定' : 'To',
    category: language === 'ja' ? 'カテゴリ' : 'Category',
    receivable: language === 'ja' ? '立替金' : 'Receivable',
    deposit: language === 'ja' ? '返金先' : 'Reimbursement Deposit',
    amount: language === 'ja' ? '金額' : 'Amount',
    ownShare: language === 'ja' ? '自分負担' : 'Own Share',
    advance: language === 'ja' ? '立替額' : 'Advance',
    reimbursed: language === 'ja' ? '返金済み' : 'Reimbursed',
    preview: language === 'ja' ? '生成プレビュー' : 'Preview',
    post: language === 'ja' ? '取引を作成' : 'Post Transactions',
    noTemplates: language === 'ja' ? 'クイックテンプレートはまだありません' : 'No quick templates yet',
});

export const quickHelp = (language: LanguageCode) => ({
    tray: language === 'ja' ? 'テンプレートを並べる分類です。生活カテゴリごとにまとめます。' : 'A group that holds related templates, like category trays on a phone.',
    templateName: language === 'ja' ? 'タイルに表示される名前です。日々押しやすい短い名前がおすすめです。' : 'The label shown on the tile. Short daily-use names work best.',
    kind: language === 'ja' ? '入力内容からどのTransaction種別を生成するかを決めます。' : 'Controls which transaction type is generated from the entry.',
    currency: language === 'ja' ? 'このテンプレートで使う既定通貨です。入力時にも変更できます。' : 'Default currency for this template. You can still change it while posting.',
    from: language === 'ja' ? '支払い口座、クレジット、または振替元です。' : 'Payment account, credit liability, or transfer source.',
    to: language === 'ja' ? '費目、返金先、負債など生成先の勘定です。' : 'Destination account such as expense, deposit account, or liability.',
    category: language === 'ja' ? 'Transactionのcategoryに保存され、一覧や分析の分類に使います。' : 'Saved to the transaction category for filtering and analysis.',
    receivable: language === 'ja' ? '立替分を一時的に置く資産勘定です。返金でここから減らします。' : 'Asset account used to hold advances until they are reimbursed.',
    deposit: language === 'ja' ? '返金を受け取る現金・銀行などの資産勘定です。' : 'Asset account where reimbursement is received.',
    amount: language === 'ja' ? '支払った合計金額です。立替ありの場合は自分負担と立替額に分解します。' : 'Total paid amount. Advance templates split it into own share and advance.',
    ownShare: language === 'ja' ? '合計金額のうち自分の支出として記録する金額です。' : 'Part of the total recorded as your own expense.',
    advance: language === 'ja' ? '他者分として一時的に立て替えた金額です。' : 'Part temporarily paid on behalf of someone else.',
    reimbursed: language === 'ja' ? 'オンにすると立替返金のTransferも同時に生成します。' : 'When enabled, also creates the reimbursement transfer.',
    preview: language === 'ja' ? '保存前に実際に作られるTransactionを確認できます。' : 'Shows the exact transactions before they are posted.',
});

export const InfoTip = ({ text }: { text: string }) => (
    <span className="inline-flex text-slate-500 hover:text-emerald-300 align-middle" title={text} aria-label={text}>
        <Info size={12} />
    </span>
);

export const configAccountId = (template: QuickTemplate | undefined, key: string) => {
    const value = template?.config?.[key];
    if (typeof value === 'number') return value;
    if (typeof value === 'string' && value) return Number(value);
    return undefined;
};

export const quickPresetFor = (template: QuickTemplate) => {
    const key = typeof template.config?.preset_key === 'string' ? template.config.preset_key : '';
    return QUICK_PRESETS.find((preset) => preset.key === key)
        || QUICK_PRESETS.find((preset) => preset.name === template.name || preset.category === template.category);
};

export const buildQuickTransactions = ({
    selectedTemplate,
    quickEntry,
    accounts,
    currentCurrency,
}: {
    selectedTemplate: QuickTemplate | undefined;
    quickEntry: QuickEntry;
    accounts: AccountItem[];
    currentCurrency: string;
}): { transactions: Array<Omit<Transaction, 'id'>>; error?: string } => {
    const accountById = (id: number | string | null | undefined) => {
        if (id === null || id === undefined || id === '') return undefined;
        return accounts.find((account) => account.id === Number(id));
    };

    if (!selectedTemplate) return { transactions: [], error: 'Select a quick template' };
    const kind = selectedTemplate.template_kind as QuickTemplateKind;
    const amount = Number(quickEntry.amount || 0);
    const ownAmount = Number(quickEntry.ownAmount || 0);
    const advanceAmount = Number(quickEntry.advanceAmount || 0);
    const paymentAccount = accountById(quickEntry.payment_account_id);
    const expenseAccount = accountById(quickEntry.expense_account_id);
    const receivableAccount = accountById(quickEntry.receivable_account_id || quickEntry.payment_account_id);
    const reimbursementAccount = accountById(quickEntry.reimbursement_account_id || quickEntry.expense_account_id);
    const description = quickEntry.description.trim() || selectedTemplate.name;
    const category = selectedTemplate.category || expenseAccount?.name || selectedTemplate.tray;
    const base = {
        date: quickEntry.date,
        currency: quickEntry.currency || selectedTemplate.default_currency || currentCurrency,
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
                category: selectedTemplate.category || 'reimbursement',
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
                category: selectedTemplate.category || 'transfer',
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
                category: selectedTemplate.category || expenseAccount.name,
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
