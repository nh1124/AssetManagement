import {
    Brain,
    BriefcaseBusiness,
    Car,
    CircleHelp,
    CreditCard,
    Cross,
    Film,
    Home,
    Info,
    PiggyBank,
    RotateCcw,
    ShoppingBasket,
    Smartphone,
    Sofa,
    Sparkles,
    Train,
    Wallet,
} from 'lucide-react';
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
    | 'income'
    | 'reimbursement'
    | 'transfer'
    | 'debt_payment';

export type QuickTemplateGroup = 'expense' | 'income' | 'transfer';

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
    group: QuickTemplateGroup;
    fromTypes: string[];
    toTypes: string[];
}> = [
    { value: 'simple_expense', label: '支出', group: 'expense', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['expense', 'item'] },
    { value: 'credit_expense', label: '支出（クレカ）', group: 'expense', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['expense', 'item'] },
    { value: 'expense_with_advance', label: '支出＋立替', group: 'expense', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['expense', 'item'] },
    { value: 'income', label: '収入', group: 'income', fromTypes: ['income'], toTypes: ['asset', 'item', 'liability'] },
    { value: 'reimbursement', label: '返金・精算', group: 'transfer', fromTypes: ['asset', 'item'], toTypes: ['asset', 'item'] },
    { value: 'transfer', label: '口座移動', group: 'transfer', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['asset', 'item', 'liability', 'income'] },
    { value: 'debt_payment', label: '負債支払', group: 'transfer', fromTypes: ['asset', 'item', 'income'], toTypes: ['liability'] },
];

export const QUICK_KIND_RULES = Object.fromEntries(
    QUICK_TEMPLATE_KINDS.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<QuickTemplateKind, { fromTypes: string[]; toTypes: string[] }>;

export const quickKindLabel = (kind: string) =>
    QUICK_TEMPLATE_KINDS.find((option) => option.value === kind)?.label ?? kind;

export const QUICK_TEMPLATE_GROUPS: Array<{ value: QuickTemplateGroup; label: string }> = [
    { value: 'expense', label: '支出' },
    { value: 'income', label: '収入' },
    { value: 'transfer', label: '移動' },
];

export const quickKindGroup = (kind: string): QuickTemplateGroup =>
    QUICK_TEMPLATE_KINDS.find((option) => option.value === kind)?.group ?? 'expense';

export const QUICK_PRESETS: QuickPreset[] = [
    {
        key: 'housing_utilities',
        tray: '固定費',
        name: '住居・光熱',
        template_kind: 'simple_expense',
        category: '固定費/住居・光熱',
        icon: Home,
        color: 'text-rose-400',
        accountHints: ['bill', 'rent', 'housing', 'utilities', 'electricity', 'gas', 'water', 'internet', '住居費', '家賃', '水道光熱費', '通信費'],
        description: {
            ja: '家賃、管理費、電気、ガス、水道など住まいの固定費を記録します。',
            en: 'Records rent, utilities, internet, and other recurring home bills.',
        },
    },
    {
        key: 'communications_mobile',
        tray: '固定費',
        name: '通信・サブスク',
        template_kind: 'simple_expense',
        category: '固定費/通信・サブスク',
        icon: Smartphone,
        color: 'text-cyan-400',
        accountHints: ['mobile', 'phone', 'sim', 'internet', 'subscription', '通信費', 'スマホ', '携帯料金', 'SIM', 'サブスク'],
        description: {
            ja: 'スマホ、SIM、自宅回線、クラウド、定額サービスなどを記録します。',
            en: 'Records phone, SIM, internet, cloud, and recurring subscription costs.',
        },
    },
    {
        key: 'food_groceries',
        tray: '食費',
        name: '食材・日常食',
        template_kind: 'simple_expense',
        category: '食費/食材・日常食',
        icon: ShoppingBasket,
        color: 'text-emerald-400',
        accountHints: ['food', 'grocery', 'groceries', 'supermarket', '食費', '食材', 'スーパー', '米', '肉', '野菜', '調味料'],
        description: {
            ja: 'スーパー、食材、飲料、軽食など日常的な食費を記録します。',
            en: 'Records groceries, dining, coffee, snacks, and everyday food spending.',
        },
    },
    {
        key: 'food_dining_out',
        tray: '食費',
        name: '外食・カフェ',
        template_kind: 'expense_with_advance',
        category: '食費/外食・カフェ',
        icon: Sparkles,
        color: 'text-orange-400',
        accountHints: ['food', 'dining', 'restaurant', 'cafe', '食費', '外食', 'ランチ', '飲み会', 'カフェ', 'ファストフード'],
        description: {
            ja: '外食、カフェ、飲み会などを記録します。割り勘や立替にも対応します。',
            en: 'Records dining, cafes, and drinks, with optional split-bill handling.',
        },
    },
    {
        key: 'daily_consumables',
        tray: '生活',
        name: '日用品',
        template_kind: 'simple_expense',
        category: '生活/日用品',
        icon: Sofa,
        color: 'text-amber-400',
        accountHints: ['daily', 'consumables', 'household', 'storage', 'cleaning', 'kitchen', '日用品', '消耗品', '生活雑貨', '衛生用品'],
        description: {
            ja: '消耗品、生活雑貨、衛生用品、収納・掃除用品などを記録します。',
            en: 'Records consumables, household goods, hygiene items, and small home supplies.',
        },
    },
    {
        key: 'beauty_skincare',
        tray: '生活',
        name: '衣服・身だしなみ',
        template_kind: 'simple_expense',
        category: '生活/衣服・身だしなみ',
        icon: Sparkles,
        color: 'text-pink-400',
        accountHints: ['beauty', 'skincare', 'hair', 'clothing', 'fashion', '美容', '身だしなみ', 'スキンケア', 'ヘアケア', '服飾'],
        description: {
            ja: '衣服、散髪、スキンケア、身だしなみ用品などを記録します。',
            en: 'Records grooming, skincare, haircare, clothing, and personal maintenance.',
        },
    },
    {
        key: 'health_medical',
        tray: '医療・健康',
        name: '医療・健康',
        template_kind: 'simple_expense',
        category: '医療・健康',
        icon: Cross,
        color: 'text-teal-400',
        accountHints: ['medical', 'clinic', 'medicine', 'health', 'gym', 'supplement', '医療', '健康', '医療費', '病院', '薬代', 'ジム'],
        description: {
            ja: '病院、薬、サプリ、ジム、健康維持の支出を記録します。',
            en: 'Records clinics, medicine, supplements, gym fees, and health maintenance.',
        },
    },
    {
        key: 'transport_commute',
        tray: '交通',
        name: '通勤・会社対応',
        template_kind: 'simple_expense',
        category: '交通/通勤・会社対応',
        icon: Train,
        color: 'text-blue-400',
        accountHints: ['transport', 'commute', 'train', 'bus', 'company', 'work', '交通費', '通勤', '会社', '仕事', '電車', 'バス', '定期券'],
        description: {
            ja: '通勤、定期券、会社都合の移動、業務関連の交通費を記録します。',
            en: 'Records trains, buses, taxis, commuter passes, and personal travel.',
        },
    },
    {
        key: 'transport_personal',
        tray: '交通',
        name: '私用移動',
        template_kind: 'simple_expense',
        category: '交通/私用移動',
        icon: Car,
        color: 'text-indigo-400',
        accountHints: ['transport', 'taxi', 'rental car', 'personal', '交通費', '私用移動', 'タクシー', '新幹線', 'レンタカー', '駐輪場'],
        description: {
            ja: '休日や私用の電車、タクシー、レンタカー、駐輪場などを記録します。',
            en: 'Records personal travel such as taxis, trains, rental cars, and bike parking.',
        },
    },
    {
        key: 'learning_services',
        tray: '仕事・学習',
        name: '仕事道具・学習',
        template_kind: 'simple_expense',
        category: '仕事・学習/仕事道具・学習',
        icon: Brain,
        color: 'text-violet-400',
        accountHints: ['learning', 'subscription', 'ai', 'udemy', 'book', 'software', 'github', 'ide', 'api', '学習', '自己投資', 'サービス', '書籍', 'IT', '開発'],
        description: {
            ja: '書籍、資格、学習サービス、開発ツール、仕事用ソフトなどを記録します。',
            en: 'Records learning services, books, software tools, APIs, and development costs.',
        },
    },
    {
        key: 'social_drinks',
        tray: '交際',
        name: '会食・贈答',
        template_kind: 'expense_with_advance',
        category: '交際/会食・贈答',
        icon: Sparkles,
        color: 'text-red-400',
        accountHints: ['social', 'drinks', 'dining', 'gift', 'present', 'dating', '交際費', '飲み会', '贈答', '恋愛', '婚活'],
        description: {
            ja: '会食、飲み会、贈答、デートなどの交際費を記録します。割り勘や立替にも対応します。',
            en: 'Records meals, drinks, gifts, dating, and other social spending, with split-bill support.',
        },
    },
    {
        key: 'hobby_entertainment',
        tray: '趣味・娯楽',
        name: '趣味・娯楽',
        template_kind: 'simple_expense',
        category: '趣味・娯楽',
        icon: Film,
        color: 'text-purple-400',
        accountHints: ['entertainment', 'movie', 'game', 'music', 'streaming', 'leisure', 'travel', 'event', '趣味', '娯楽', 'エンタメ', 'レジャー'],
        description: {
            ja: '映画、ゲーム、配信、旅行、イベントなど趣味と娯楽を記録します。',
            en: 'Records entertainment, hobbies, travel, events, and leisure.',
        },
    },
    {
        key: 'other_unknown',
        tray: 'その他',
        name: '未分類・調整',
        template_kind: 'simple_expense',
        category: 'その他/未分類・調整',
        icon: CircleHelp,
        color: 'text-slate-400',
        accountHints: ['unknown', 'uncategorized', 'other', 'adjustment', 'unexpected', 'その他', '不明', '未分類', '調整', '臨時費'],
        description: {
            ja: 'あとで分類する支出、調整、臨時の支出を一時的に記録します。',
            en: 'Records uncategorized, unusual, or temporary spending.',
        },
    },
    {
        key: 'income_salary',
        tray: '収入',
        name: '給与・賞与',
        template_kind: 'income',
        category: '収入/給与・賞与',
        icon: BriefcaseBusiness,
        color: 'text-emerald-300',
        accountHints: ['income', 'salary', 'payroll', 'bonus', 'allowance', '勤務収入', '給与', '賞与', 'ボーナス', '手当'],
        description: {
            ja: '給与、賞与、手当など勤務先からの収入を記録します。',
            en: 'Records salary, payroll, bonuses, and allowances.',
        },
    },
    {
        key: 'income_investment_return',
        tray: '収入',
        name: '副業・臨時収入',
        template_kind: 'income',
        category: '収入/副業・臨時収入',
        icon: PiggyBank,
        color: 'text-lime-300',
        accountHints: ['income', 'interest', 'dividend', 'refund', 'rebate', 'temporary', 'gift', 'sale', '資産収入', '返金', '還付', '臨時収入'],
        description: {
            ja: '副業、配当、売却益、お祝い、謝礼など一時的または勤務外の収入を記録します。',
            en: 'Records refunds, rebates, dividends, side income, and one-time income.',
        },
    },
    {
        key: 'income_refund_rebate',
        tray: '収入',
        name: '返金・還付',
        template_kind: 'income',
        category: '収入/返金・還付',
        icon: RotateCcw,
        color: 'text-cyan-300',
        accountHints: ['income', 'refund', 'rebate', 'cashback', '返金', '還付', 'キャッシュバック'],
        description: {
            ja: '返金、還付、キャッシュバックなどを収入として記録します。',
            en: 'Records refunds, rebates, and cashback as income.',
        },
    },
    {
        key: 'transfer_between_accounts',
        tray: '口座移動',
        name: '口座間移動',
        template_kind: 'transfer',
        category: '口座移動/口座間移動',
        icon: Wallet,
        color: 'text-sky-300',
        accountHints: ['bank', 'cash', 'transfer', '口座移動', '口座間移動', '振替', '銀行', '現金'],
        description: {
            ja: '銀行口座、現金、電子マネー間の資金移動を記録します。',
            en: 'Records money movement between bank, cash, and wallet accounts.',
        },
    },
    {
        key: 'transfer_savings',
        tray: '口座移動',
        name: '貯蓄・投資振替',
        template_kind: 'transfer',
        category: '口座移動/貯蓄・投資振替',
        icon: PiggyBank,
        color: 'text-yellow-300',
        accountHints: ['savings', 'deposit', 'emergency fund', 'investment', 'brokerage', 'nisa', '口座移動', '貯蓄', '投資移動', '証券', 'NISA'],
        description: {
            ja: '貯蓄、生活防衛資金、証券口座、投資用口座への資金移動を記録します。',
            en: 'Records transfers into savings, emergency funds, or investment accounts.',
        },
    },
    {
        key: 'transfer_credit_card_payment',
        tray: '支払・精算',
        name: 'クレカ・ローン支払',
        template_kind: 'debt_payment',
        category: '支払・精算/クレカ・ローン支払',
        icon: CreditCard,
        color: 'text-orange-300',
        accountHints: ['credit card', 'card', 'liability', 'loan', 'debt', '負債支払', 'クレカ', 'カード', 'ローン', '返済'],
        description: {
            ja: 'クレジットカード、未払金、ローン、分割払いの返済を記録します。',
            en: 'Records credit-card, payable, loan, and installment repayments.',
        },
    },
    {
        key: 'transfer_reimbursement',
        tray: '支払・精算',
        name: '立替返金・会社精算',
        template_kind: 'reimbursement',
        category: '支払・精算/立替返金・会社精算',
        icon: RotateCcw,
        color: 'text-cyan-300',
        accountHints: ['receivable', 'advance', 'reimbursement', 'company', '立替精算', '立替金', '返金', '会社精算', '精算'],
        description: {
            ja: '立替金、会社精算、交通費精算などの返金を記録します。',
            en: 'Records reimbursement received from receivables into cash or bank.',
        },
    },
];

const QUICK_PRESET_KEYS = new Set(QUICK_PRESETS.map((preset) => preset.key));

export const quickPresetKey = (template: QuickTemplate | undefined) =>
    typeof template?.config?.preset_key === 'string' ? template.config.preset_key : '';

export const isVisibleQuickTemplate = (template: QuickTemplate) => {
    const key = quickPresetKey(template);
    return !key || QUICK_PRESET_KEYS.has(key);
};

export const filterVisibleQuickTemplates = (templates: QuickTemplate[]) => {
    const activeTemplates = templates.filter((template) => template.is_active);
    const visibleTemplates = activeTemplates.filter(isVisibleQuickTemplate);
    return visibleTemplates.length > 0 ? visibleTemplates : activeTemplates;
};

export const quickTemplateDisplay = (template: QuickTemplate) => {
    const preset = quickPresetFor(template);
    return {
        tray: preset?.tray || template.tray,
        name: preset?.name || template.name,
        category: preset?.category || template.category || template.tray || template.name,
        description: preset?.description.ja || template.description || quickKindLabel(template.template_kind),
    };
};

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
    const display = quickTemplateDisplay(selectedTemplate);
    const description = quickEntry.description.trim() || display.name;
    const category = display.category || expenseAccount?.name;
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
                category: display.category || 'reimbursement',
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
                category: display.category || 'transfer',
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
                category: display.category || expenseAccount.name,
                from_account_id: paymentAccount.id,
                to_account_id: expenseAccount.id,
            }],
        };
    }

    if (kind === 'income') {
        if (!paymentAccount || !expenseAccount) return { transactions: [], error: 'Income source and destination accounts are required' };
        return {
            transactions: [{
                ...base,
                description,
                amount,
                type: 'Income',
                category: display.category || paymentAccount.name,
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
                description: `${description} 自分負担`,
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
                description: `${description} 立替`,
                amount: resolvedAdvance,
                type: isCreditPayment ? 'CreditAssetPurchase' : 'Transfer',
                category: `${category}/立替`,
                from_account_id: paymentAccount.id,
                to_account_id: receivableAccount.id,
            });
        }
        if (quickEntry.reimbursementReceived && resolvedAdvance > 0) {
            if (!receivableAccount || !reimbursementAccount) return { transactions: [], error: 'Deposit account is required for reimbursement' };
            transactions.push({
                ...base,
                description: `${description} 精算`,
                amount: resolvedAdvance,
                type: 'Transfer',
                category: `${category}/精算`,
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
            type: isCreditPayment ? 'CreditExpense' : 'Expense',
            category,
            from_account_id: paymentAccount.id,
            to_account_id: expenseAccount.id,
        }],
    };
};
