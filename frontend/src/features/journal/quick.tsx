import {
    BookOpen,
    Brain,
    BriefcaseBusiness,
    Car,
    CircleHelp,
    CircleDollarSign,
    Coffee,
    Coins,
    CreditCard,
    Cross,
    Dumbbell,
    Film,
    Gift,
    GraduationCap,
    HandCoins,
    HeartHandshake,
    HeartPulse,
    Home,
    Info,
    Landmark,
    Laptop,
    Monitor,
    PiggyBank,
    RotateCcw,
    Router,
    Scissors,
    Server,
    Shield,
    Shirt,
    ShoppingBag,
    ShoppingBasket,
    Smartphone,
    Sofa,
    Sparkles,
    SprayCan,
    SquareCode,
    Tent,
    Train,
    TrendingUp,
    Truck,
    Utensils,
    Wallet,
    Wifi,
    Wine,
    Wrench,
    Zap,
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
    { value: 'simple_expense', label: 'Expense', group: 'expense', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['expense', 'item'] },
    { value: 'credit_expense', label: 'Expense (credit default)', group: 'expense', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['expense', 'item'] },
    { value: 'expense_with_advance', label: 'Expense + Advance', group: 'expense', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['expense', 'item'] },
    { value: 'income', label: 'Income', group: 'income', fromTypes: ['income'], toTypes: ['asset', 'item', 'liability'] },
    { value: 'reimbursement', label: 'Reimbursement', group: 'transfer', fromTypes: ['asset', 'item'], toTypes: ['asset', 'item'] },
    { value: 'transfer', label: 'Transfer', group: 'transfer', fromTypes: ['asset', 'item', 'liability', 'income'], toTypes: ['asset', 'item', 'liability', 'income'] },
    { value: 'debt_payment', label: 'Debt Payment', group: 'transfer', fromTypes: ['asset', 'item', 'income'], toTypes: ['liability'] },
];

export const QUICK_KIND_RULES = Object.fromEntries(
    QUICK_TEMPLATE_KINDS.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<QuickTemplateKind, { fromTypes: string[]; toTypes: string[] }>;

export const quickKindLabel = (kind: string) =>
    QUICK_TEMPLATE_KINDS.find((option) => option.value === kind)?.label ?? kind;

export const QUICK_TEMPLATE_GROUPS: Array<{ value: QuickTemplateGroup; label: string }> = [
    { value: 'expense', label: 'Expense' },
    { value: 'income', label: 'Income' },
    { value: 'transfer', label: 'Transfer' },
];

export const quickKindGroup = (kind: string): QuickTemplateGroup =>
    QUICK_TEMPLATE_KINDS.find((option) => option.value === kind)?.group ?? 'expense';

export const QUICK_PRESETS: QuickPreset[] = [
    {
        key: 'housing_rent',
        tray: '住居費',
        name: '家賃・社宅費',
        template_kind: 'simple_expense',
        category: '住居費/家賃・社宅費',
        icon: Home,
        color: 'text-rose-400',
        accountHints: ['rent', 'housing', '住居費', '家賃', '社宅', '共益費', '管理費'],
        description: {
            ja: '家賃、社宅使用料、共益費、管理費などを記録します。',
            en: 'Records rent, company housing fees, common charges, and maintenance fees.',
        },
    },
    {
        key: 'housing_utilities',
        tray: '住居費',
        name: '水道光熱費',
        template_kind: 'simple_expense',
        category: '住居費/水道光熱費',
        icon: Zap,
        color: 'text-amber-400',
        accountHints: ['utilities', 'electricity', 'gas', 'water', '住居費', '水道光熱費', '電気', 'ガス', '水道'],
        description: {
            ja: '電気、ガス、水道などを記録します。',
            en: 'Records electricity, gas, and water bills.',
        },
    },
    {
        key: 'housing_connectivity_equipment',
        tray: '住居費',
        name: '通信・設備',
        template_kind: 'simple_expense',
        category: '住居費/通信・設備',
        icon: Wifi,
        color: 'text-sky-400',
        accountHints: ['wifi', 'router', 'equipment', '住居費', '通信', '設備', 'ルーター', '宅配ボックス'],
        description: {
            ja: 'Wi-Fi、ルーター、宅配ボックス、設備利用料などを記録します。',
            en: 'Records Wi-Fi, routers, parcel lockers, and equipment usage fees.',
        },
    },
    {
        key: 'food_groceries',
        tray: '食費',
        name: '食材',
        template_kind: 'simple_expense',
        category: '食費/食材',
        icon: ShoppingBasket,
        color: 'text-emerald-400',
        accountHints: ['food', 'grocery', 'groceries', 'supermarket', '食費', '食材', 'スーパー', '米', '肉', '野菜', '調味料'],
        description: {
            ja: 'スーパー、米、肉、野菜、調味料などを記録します。',
            en: 'Records groceries such as supermarket purchases, rice, meat, vegetables, and seasonings.',
        },
    },
    {
        key: 'food_dining_out',
        tray: '食費',
        name: '外食',
        template_kind: 'expense_with_advance',
        category: '食費/外食',
        icon: Utensils,
        color: 'text-orange-400',
        accountHints: ['food', 'dining', 'restaurant', 'cafe', '食費', '外食', 'ランチ', '飲み会', 'カフェ', 'ファストフード'],
        description: {
            ja: 'ランチ、飲み会、カフェ、ファストフードなどを記録します。割り勘や立替にも対応します。',
            en: 'Records dining out such as lunch, drinks, cafes, and fast food, with optional split-bill handling.',
        },
    },
    {
        key: 'food_drinks_treats',
        tray: '食費',
        name: '飲料・嗜好品',
        template_kind: 'simple_expense',
        category: '食費/飲料・嗜好品',
        icon: Coffee,
        color: 'text-yellow-400',
        accountHints: ['food', 'coffee', 'snack', 'protein', '食費', '飲料', '嗜好品', 'コーヒー', 'プロテイン', '菓子', '軽食'],
        description: {
            ja: 'コーヒー、プロテイン、菓子、軽食などを記録します。',
            en: 'Records drinks and treats such as coffee, protein, snacks, and light meals.',
        },
    },
    {
        key: 'daily_consumables',
        tray: '日用品',
        name: '消耗品',
        template_kind: 'simple_expense',
        category: '日用品/消耗品',
        icon: SprayCan,
        color: 'text-amber-400',
        accountHints: ['daily', 'consumables', 'detergent', '日用品', '消耗品', '洗剤', 'ティッシュ', 'トイレットペーパー', 'ゴミ袋'],
        description: {
            ja: '洗剤、ティッシュ、トイレットペーパー、ゴミ袋などを記録します。',
            en: 'Records consumables such as detergent, tissues, toilet paper, and trash bags.',
        },
    },
    {
        key: 'daily_household_goods',
        tray: '日用品',
        name: '生活雑貨',
        template_kind: 'simple_expense',
        category: '日用品/生活雑貨',
        icon: Sofa,
        color: 'text-lime-400',
        accountHints: ['daily', 'household', 'storage', 'cleaning', 'kitchen', '日用品', '生活雑貨', 'ハンガー', '収納用品', '掃除用品', 'キッチン用品'],
        description: {
            ja: 'ハンガー、収納用品、掃除用品、キッチン用品などを記録します。',
            en: 'Records household goods such as hangers, storage items, cleaning tools, and kitchen supplies.',
        },
    },
    {
        key: 'daily_hygiene',
        tray: '日用品',
        name: '衛生用品',
        template_kind: 'simple_expense',
        category: '日用品/衛生用品',
        icon: ShoppingBag,
        color: 'text-cyan-400',
        accountHints: ['daily', 'hygiene', 'mask', '日用品', '衛生用品', '歯ブラシ', '歯磨き粉', 'シェーバー', 'マスク'],
        description: {
            ja: '歯ブラシ、歯磨き粉、シェーバー用品、マスクなどを記録します。',
            en: 'Records hygiene goods such as toothbrushes, toothpaste, shaving items, and masks.',
        },
    },
    {
        key: 'beauty_skincare',
        tray: '美容・身だしなみ',
        name: 'スキンケア',
        template_kind: 'simple_expense',
        category: '美容・身だしなみ/スキンケア',
        icon: Sparkles,
        color: 'text-pink-400',
        accountHints: ['beauty', 'skincare', '美容', '身だしなみ', 'スキンケア', '洗顔', '化粧水', '日焼け止め', '保湿剤'],
        description: {
            ja: '洗顔、化粧水、日焼け止め、保湿剤などを記録します。',
            en: 'Records skincare such as face wash, toner, sunscreen, and moisturizer.',
        },
    },
    {
        key: 'beauty_haircare',
        tray: '美容・身だしなみ',
        name: 'ヘアケア',
        template_kind: 'simple_expense',
        category: '美容・身だしなみ/ヘアケア',
        icon: Scissors,
        color: 'text-violet-400',
        accountHints: ['beauty', 'hair', '美容', '身だしなみ', 'ヘアケア', '散髪', 'ワックス', 'ヘアスプレー', 'シャンプー'],
        description: {
            ja: '散髪、ワックス、ヘアスプレー、シャンプーなどを記録します。',
            en: 'Records haircare such as haircuts, wax, hair spray, and shampoo.',
        },
    },
    {
        key: 'beauty_clothing',
        tray: '美容・身だしなみ',
        name: '服飾',
        template_kind: 'simple_expense',
        category: '美容・身だしなみ/服飾',
        icon: Shirt,
        color: 'text-slate-300',
        accountHints: ['clothing', 'fashion', 'shopping', '美容', '身だしなみ', '服飾', 'スーツ', 'シャツ', '靴', '下着', 'カバン'],
        description: {
            ja: 'スーツ、シャツ、靴、下着、カバンなどを記録します。',
            en: 'Records clothing and accessories such as suits, shirts, shoes, underwear, and bags.',
        },
    },
    {
        key: 'health_medical',
        tray: '医療・健康',
        name: '医療費',
        template_kind: 'simple_expense',
        category: '医療・健康/医療費',
        icon: Cross,
        color: 'text-teal-400',
        accountHints: ['medical', 'clinic', 'medicine', '医療', '健康', '医療費', '病院', '歯科', '皮膚科', '薬代'],
        description: {
            ja: '病院、歯科、皮膚科、薬代などを記録します。',
            en: 'Records medical costs such as clinics, dentistry, dermatology, and medicine.',
        },
    },
    {
        key: 'health_maintenance',
        tray: '医療・健康',
        name: '健康維持',
        template_kind: 'simple_expense',
        category: '医療・健康/健康維持',
        icon: Dumbbell,
        color: 'text-green-400',
        accountHints: ['health', 'gym', 'supplement', 'protein', '医療', '健康', '健康維持', 'サプリ', '整腸薬', 'プロテイン', 'ジム'],
        description: {
            ja: 'サプリ、整腸薬、プロテイン、ジムなどを記録します。',
            en: 'Records health maintenance such as supplements, digestive medicine, protein, and gym fees.',
        },
    },
    {
        key: 'health_beauty_medical',
        tray: '医療・健康',
        name: '美容医療',
        template_kind: 'simple_expense',
        category: '医療・健康/美容医療',
        icon: HeartPulse,
        color: 'text-fuchsia-400',
        accountHints: ['medical', 'beauty', 'clinic', '医療', '健康', '美容医療', '毛穴治療', '脱毛', '肌治療', 'カウンセリング'],
        description: {
            ja: '毛穴治療、脱毛、肌治療、カウンセリングなどを記録します。',
            en: 'Records aesthetic medicine such as pore treatment, hair removal, skin treatment, and counseling.',
        },
    },
    {
        key: 'transport_commute',
        tray: '交通費',
        name: '通勤',
        template_kind: 'simple_expense',
        category: '交通費/通勤',
        icon: Train,
        color: 'text-blue-400',
        accountHints: ['transport', 'commute', 'train', 'bus', '交通費', '通勤', '電車', 'バス', '定期券'],
        description: {
            ja: '電車、バス、定期券など通勤費を記録します。',
            en: 'Records commuting costs such as trains, buses, and commuter passes.',
        },
    },
    {
        key: 'transport_personal',
        tray: '交通費',
        name: '私用移動',
        template_kind: 'simple_expense',
        category: '交通費/私用移動',
        icon: Car,
        color: 'text-indigo-400',
        accountHints: ['transport', 'taxi', 'rental car', '交通費', '私用移動', 'タクシー', '新幹線', 'レンタカー', '駐輪場'],
        description: {
            ja: 'タクシー、新幹線、レンタカー、駐輪場などを記録します。',
            en: 'Records personal travel such as taxis, bullet trains, rental cars, and bike parking.',
        },
    },
    {
        key: 'communications_mobile',
        tray: '通信費',
        name: 'スマホ',
        template_kind: 'simple_expense',
        category: '通信費/スマホ',
        icon: Smartphone,
        color: 'text-cyan-400',
        accountHints: ['mobile', 'phone', 'sim', '通信費', 'スマホ', '携帯料金', '端末代', 'SIM'],
        description: {
            ja: '携帯料金、端末代、SIMなどを記録します。',
            en: 'Records mobile costs such as phone bills, device payments, and SIM fees.',
        },
    },
    {
        key: 'communications_network',
        tray: '通信費',
        name: 'サブ回線・ネット',
        template_kind: 'simple_expense',
        category: '通信費/サブ回線・ネット',
        icon: Router,
        color: 'text-sky-400',
        accountHints: ['internet', 'wifi', 'cloud', '通信費', 'サブ回線', 'ネット', '自宅回線', 'モバイルWi-Fi', 'クラウド通信'],
        description: {
            ja: '自宅回線、モバイルWi-Fi、クラウド通信などを記録します。',
            en: 'Records network costs such as home internet, mobile Wi-Fi, and cloud connectivity.',
        },
    },
    {
        key: 'learning_certification',
        tray: '学習・自己投資',
        name: '資格',
        template_kind: 'simple_expense',
        category: '学習・自己投資/資格',
        icon: GraduationCap,
        color: 'text-yellow-300',
        accountHints: ['learning', 'certification', 'exam', '学習', '自己投資', '資格', '受験料', '参考書', '問題集', '講座'],
        description: {
            ja: '受験料、参考書、問題集、講座などを記録します。',
            en: 'Records certification costs such as exam fees, study guides, workbooks, and courses.',
        },
    },
    {
        key: 'learning_books',
        tray: '学習・自己投資',
        name: '書籍',
        template_kind: 'simple_expense',
        category: '学習・自己投資/書籍',
        icon: BookOpen,
        color: 'text-lime-400',
        accountHints: ['book', 'kindle', 'learning', '学習', '自己投資', '書籍', '技術書', 'ビジネス書', 'Kindle'],
        description: {
            ja: '技術書、ビジネス書、Kindleなどを記録します。',
            en: 'Records books such as technical books, business books, and Kindle purchases.',
        },
    },
    {
        key: 'learning_services',
        tray: '学習・自己投資',
        name: 'サービス',
        template_kind: 'simple_expense',
        category: '学習・自己投資/サービス',
        icon: Brain,
        color: 'text-violet-400',
        accountHints: ['learning', 'subscription', 'ai', 'udemy', '学習', '自己投資', 'サービス', 'ChatGPT', 'Claude', 'Gemini', 'Udemy', '学習アプリ'],
        description: {
            ja: 'ChatGPT、Claude、Gemini、Udemy、学習アプリなどを記録します。',
            en: 'Records learning services such as ChatGPT, Claude, Gemini, Udemy, and study apps.',
        },
    },
    {
        key: 'it_server',
        tray: 'IT・開発',
        name: 'サーバー',
        template_kind: 'simple_expense',
        category: 'IT・開発/サーバー',
        icon: Server,
        color: 'text-emerald-400',
        accountHints: ['server', 'vps', 'domain', 'cloudflare', 'IT', '開発', 'サーバー', '自宅サーバ', 'ドメイン'],
        description: {
            ja: 'VPS、自宅サーバ部品、ドメイン、Cloudflareなどを記録します。',
            en: 'Records server costs such as VPS, home server parts, domains, and Cloudflare.',
        },
    },
    {
        key: 'it_software',
        tray: 'IT・開発',
        name: 'ソフトウェア',
        template_kind: 'simple_expense',
        category: 'IT・開発/ソフトウェア',
        icon: SquareCode,
        color: 'text-blue-300',
        accountHints: ['software', 'github', 'ide', 'api', 'IT', '開発', 'ソフトウェア', '有料ツール', 'API利用料'],
        description: {
            ja: 'GitHub、有料ツール、IDE、API利用料などを記録します。',
            en: 'Records software costs such as GitHub, paid tools, IDEs, and API usage.',
        },
    },
    {
        key: 'it_gadgets',
        tray: 'IT・開発',
        name: 'ガジェット',
        template_kind: 'simple_expense',
        category: 'IT・開発/ガジェット',
        icon: Monitor,
        color: 'text-slate-300',
        accountHints: ['gadget', 'pc', 'keyboard', 'mouse', 'monitor', 'IT', '開発', 'ガジェット', '周辺機器'],
        description: {
            ja: 'PC周辺機器、マウス、キーボード、モニターなどを記録します。',
            en: 'Records gadgets such as PC peripherals, mice, keyboards, and monitors.',
        },
    },
    {
        key: 'social_drinks',
        tray: '交際費',
        name: '飲み会',
        template_kind: 'expense_with_advance',
        category: '交際費/飲み会',
        icon: Wine,
        color: 'text-red-400',
        accountHints: ['social', 'drinks', 'dining', '交際費', '飲み会', '会社飲み会', '友人', '食事'],
        description: {
            ja: '会社飲み会、友人との食事などを記録します。割り勘や立替にも対応します。',
            en: 'Records social drinks and meals, with optional split-bill handling.',
        },
    },
    {
        key: 'social_gifts',
        tray: '交際費',
        name: '贈答',
        template_kind: 'simple_expense',
        category: '交際費/贈答',
        icon: Gift,
        color: 'text-pink-400',
        accountHints: ['gift', 'present', 'social', '交際費', '贈答', 'プレゼント', '手土産', '冠婚葬祭'],
        description: {
            ja: 'プレゼント、手土産、冠婚葬祭などを記録します。',
            en: 'Records gifts such as presents, souvenirs, and ceremonial expenses.',
        },
    },
    {
        key: 'social_dating',
        tray: '交際費',
        name: '恋愛・婚活',
        template_kind: 'simple_expense',
        category: '交際費/恋愛・婚活',
        icon: HeartHandshake,
        color: 'text-rose-300',
        accountHints: ['dating', 'social', '交際費', '恋愛', '婚活', 'マッチングアプリ', 'デート代', '身だしなみ'],
        description: {
            ja: 'マッチングアプリ、デート代、身だしなみ関連などを記録します。',
            en: 'Records dating costs such as matching apps, date expenses, and grooming.',
        },
    },
    {
        key: 'hobby_entertainment',
        tray: '趣味・娯楽',
        name: 'エンタメ',
        template_kind: 'simple_expense',
        category: '趣味・娯楽/エンタメ',
        icon: Film,
        color: 'text-purple-400',
        accountHints: ['entertainment', 'movie', 'game', 'music', 'streaming', '趣味', '娯楽', 'エンタメ', '映画', 'ゲーム', '動画配信', '音楽'],
        description: {
            ja: '映画、ゲーム、動画配信、音楽などを記録します。',
            en: 'Records entertainment such as movies, games, streaming video, and music.',
        },
    },
    {
        key: 'hobby_leisure',
        tray: '趣味・娯楽',
        name: 'レジャー',
        template_kind: 'simple_expense',
        category: '趣味・娯楽/レジャー',
        icon: Tent,
        color: 'text-green-300',
        accountHints: ['leisure', 'travel', 'event', 'sports', '趣味', '娯楽', 'レジャー', '旅行', 'イベント', 'スポーツ観戦'],
        description: {
            ja: '旅行、イベント、スポーツ観戦などを記録します。',
            en: 'Records leisure such as travel, events, and sports viewing.',
        },
    },
    {
        key: 'insurance_premiums',
        tray: '保険・税金',
        name: '保険',
        template_kind: 'simple_expense',
        category: '保険・税金/保険',
        icon: Shield,
        color: 'text-teal-300',
        accountHints: ['insurance', '保険', '税金', '医療保険', '生命保険', 'GLTD'],
        description: {
            ja: '医療保険、生命保険、GLTDなどを記録します。',
            en: 'Records insurance such as medical insurance, life insurance, and GLTD.',
        },
    },
    {
        key: 'insurance_taxes_public',
        tray: '保険・税金',
        name: '税・公的負担',
        template_kind: 'simple_expense',
        category: '保険・税金/税・公的負担',
        icon: Landmark,
        color: 'text-stone-300',
        accountHints: ['tax', 'pension', 'insurance', '保険', '税金', '公的負担', '住民税', '所得税', '年金', '健康保険'],
        description: {
            ja: '住民税、所得税、年金、健康保険などを記録します。',
            en: 'Records taxes and public burdens such as resident tax, income tax, pension, and health insurance.',
        },
    },
    {
        key: 'finance_investment',
        tray: '金融・投資',
        name: '投資',
        template_kind: 'simple_expense',
        category: '金融・投資/投資',
        icon: TrendingUp,
        color: 'text-emerald-300',
        accountHints: ['investment', 'nisa', 'fund', '金融', '投資', 'NISA', '持株会', 'iDeCo', '投信購入'],
        description: {
            ja: 'NISA、持株会、iDeCo、投信購入などを記録します。',
            en: 'Records investment outflows such as NISA, employee stock plans, iDeCo, and fund purchases.',
        },
    },
    {
        key: 'finance_savings',
        tray: '金融・投資',
        name: '貯蓄',
        template_kind: 'simple_expense',
        category: '金融・投資/貯蓄',
        icon: PiggyBank,
        color: 'text-yellow-300',
        accountHints: ['savings', 'deposit', '金融', '投資', '貯蓄', '財形', '定期預金', '生活防衛資金'],
        description: {
            ja: '財形、定期預金、生活防衛資金などを記録します。',
            en: 'Records savings outflows such as payroll savings, term deposits, and emergency funds.',
        },
    },
    {
        key: 'finance_fees',
        tray: '金融・投資',
        name: '手数料',
        template_kind: 'simple_expense',
        category: '金融・投資/手数料',
        icon: CreditCard,
        color: 'text-orange-300',
        accountHints: ['fee', 'bank', 'card', '金融', '投資', '手数料', '振込手数料', '分割手数料', 'カード手数料'],
        description: {
            ja: '振込手数料、分割手数料、カード手数料などを記録します。',
            en: 'Records fees such as transfer fees, installment fees, and card fees.',
        },
    },
    {
        key: 'special_moving',
        tray: '特別支出',
        name: '引越し',
        template_kind: 'simple_expense',
        category: '特別支出/引越し',
        icon: Truck,
        color: 'text-blue-300',
        accountHints: ['moving', 'furniture', 'appliance', 'delivery', '特別支出', '引越し', '家具', '家電', '初期費用', '配送費'],
        description: {
            ja: '家具、家電、初期費用、配送費など引越し関連を記録します。',
            en: 'Records moving costs such as furniture, appliances, initial fees, and delivery.',
        },
    },
    {
        key: 'special_large_purchase',
        tray: '特別支出',
        name: '大型購入',
        template_kind: 'simple_expense',
        category: '特別支出/大型購入',
        icon: Laptop,
        color: 'text-indigo-300',
        accountHints: ['large purchase', 'pc', 'appliance', 'furniture', '特別支出', '大型購入', 'PC', '家電', '家具', 'スーツ一式'],
        description: {
            ja: 'PC、家電、家具、スーツ一式などを記録します。',
            en: 'Records large purchases such as PCs, appliances, furniture, and full suit sets.',
        },
    },
    {
        key: 'special_unplanned',
        tray: '特別支出',
        name: '臨時費',
        template_kind: 'simple_expense',
        category: '特別支出/臨時費',
        icon: Wrench,
        color: 'text-red-300',
        accountHints: ['unexpected', 'repair', 'lost', '特別支出', '臨時費', '修理', '紛失', '急な出費'],
        description: {
            ja: '修理、紛失、急な出費などを記録します。',
            en: 'Records unplanned costs such as repairs, lost items, and sudden expenses.',
        },
    },
    {
        key: 'other_unknown',
        tray: 'その他',
        name: '不明・未分類',
        template_kind: 'simple_expense',
        category: 'その他/不明・未分類',
        icon: CircleHelp,
        color: 'text-slate-400',
        accountHints: ['unknown', 'uncategorized', 'other', 'その他', '不明', '未分類', 'あとで分類'],
        description: {
            ja: 'あとで分類する支出を一時的に記録します。',
            en: 'Records spending that will be categorized later.',
        },
    },
    {
        key: 'other_adjustment',
        tray: 'その他',
        name: '調整',
        template_kind: 'simple_expense',
        category: 'その他/調整',
        icon: RotateCcw,
        color: 'text-slate-300',
        accountHints: ['adjustment', 'refund', 'points', 'reimbursement', 'その他', '調整', '返金', 'ポイント利用', '立替精算'],
        description: {
            ja: '返金、ポイント利用、立替精算などの調整を記録します。',
            en: 'Records adjustments such as refunds, point usage, and advance settlements.',
        },
    },
    {
        key: 'income_salary',
        tray: '勤務収入',
        name: '給与',
        template_kind: 'income',
        category: '勤務収入/給与',
        icon: BriefcaseBusiness,
        color: 'text-emerald-300',
        accountHints: ['income', 'salary', 'payroll', '勤務収入', '給与', '給料', '基本給'],
        description: {
            ja: '給与、給料、基本給などの勤務収入を記録します。',
            en: 'Records employment income such as salary, payroll, and base pay.',
        },
    },
    {
        key: 'income_bonus',
        tray: '勤務収入',
        name: '賞与・手当',
        template_kind: 'income',
        category: '勤務収入/賞与・手当',
        icon: Gift,
        color: 'text-yellow-300',
        accountHints: ['income', 'bonus', 'allowance', '勤務収入', '賞与', 'ボーナス', '手当'],
        description: {
            ja: '賞与、ボーナス、各種手当などを記録します。',
            en: 'Records bonuses and allowances.',
        },
    },
    {
        key: 'income_side_job',
        tray: '事業・副業',
        name: '副業収入',
        template_kind: 'income',
        category: '事業・副業/副業収入',
        icon: Laptop,
        color: 'text-sky-300',
        accountHints: ['income', 'side job', 'freelance', '事業', '副業', '業務委託', 'フリーランス'],
        description: {
            ja: '副業、業務委託、フリーランス報酬などを記録します。',
            en: 'Records side-job, contract, and freelance income.',
        },
    },
    {
        key: 'income_investment_return',
        tray: '資産収入',
        name: '利息・配当',
        template_kind: 'income',
        category: '資産収入/利息・配当',
        icon: Coins,
        color: 'text-lime-300',
        accountHints: ['income', 'interest', 'dividend', '資産収入', '利息', '配当', '分配金'],
        description: {
            ja: '利息、配当、分配金などの資産収入を記録します。',
            en: 'Records asset income such as interest, dividends, and distributions.',
        },
    },
    {
        key: 'income_refund_rebate',
        tray: '返金・還付',
        name: '返金・還付',
        template_kind: 'income',
        category: '返金・還付/返金・還付',
        icon: RotateCcw,
        color: 'text-cyan-300',
        accountHints: ['income', 'refund', 'rebate', '返金', '還付', 'キャッシュバック'],
        description: {
            ja: '返金、還付、キャッシュバックなどを収入として記録します。',
            en: 'Records refunds, rebates, and cashback as income.',
        },
    },
    {
        key: 'income_one_time',
        tray: '臨時収入',
        name: '臨時収入',
        template_kind: 'income',
        category: '臨時収入/臨時収入',
        icon: CircleDollarSign,
        color: 'text-emerald-400',
        accountHints: ['income', 'temporary', 'gift', 'sale', '臨時収入', '売却益', 'お祝い', '謝礼'],
        description: {
            ja: '売却益、お祝い、謝礼などの一時的な収入を記録します。',
            en: 'Records one-time income such as sale proceeds, gifts, and honoraria.',
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
        name: '貯蓄振替',
        template_kind: 'transfer',
        category: '口座移動/貯蓄振替',
        icon: PiggyBank,
        color: 'text-yellow-300',
        accountHints: ['savings', 'deposit', 'emergency fund', '口座移動', '貯蓄', '定期預金', '生活防衛資金'],
        description: {
            ja: '普通口座から貯蓄、定期預金、生活防衛資金へ移す資金を記録します。',
            en: 'Records transfers from operating cash into savings, term deposits, or emergency funds.',
        },
    },
    {
        key: 'transfer_investment_funding',
        tray: '投資移動',
        name: '投資資金移動',
        template_kind: 'transfer',
        category: '投資移動/投資資金移動',
        icon: TrendingUp,
        color: 'text-emerald-300',
        accountHints: ['investment', 'brokerage', 'nisa', '投資移動', '証券', 'NISA', '投資資金'],
        description: {
            ja: '証券口座や投資用口座へ移す資金を記録します。',
            en: 'Records transfers into brokerage or investment accounts.',
        },
    },
    {
        key: 'transfer_credit_card_payment',
        tray: '負債支払',
        name: 'クレカ支払',
        template_kind: 'debt_payment',
        category: '負債支払/クレカ支払',
        icon: CreditCard,
        color: 'text-orange-300',
        accountHints: ['credit card', 'card', 'liability', '負債支払', 'クレカ', 'カード', '未払金'],
        description: {
            ja: 'クレジットカードや未払金の支払いを記録します。',
            en: 'Records credit-card or payable balance payments.',
        },
    },
    {
        key: 'transfer_loan_payment',
        tray: '負債支払',
        name: 'ローン返済',
        template_kind: 'debt_payment',
        category: '負債支払/ローン返済',
        icon: HandCoins,
        color: 'text-rose-300',
        accountHints: ['loan', 'debt', 'liability', '負債支払', 'ローン', '借入', '返済'],
        description: {
            ja: 'ローン、借入、分割払いなどの返済を記録します。',
            en: 'Records loan, borrowing, and installment repayments.',
        },
    },
    {
        key: 'transfer_reimbursement',
        tray: '立替精算',
        name: '立替返金',
        template_kind: 'reimbursement',
        category: '立替精算/立替返金',
        icon: RotateCcw,
        color: 'text-cyan-300',
        accountHints: ['receivable', 'advance', 'reimbursement', '立替精算', '立替金', '返金', '精算'],
        description: {
            ja: '立替金から現金・銀行などへ返金された精算を記録します。',
            en: 'Records reimbursement received from receivables into cash or bank.',
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

    if (kind === 'income') {
        if (!paymentAccount || !expenseAccount) return { transactions: [], error: 'Income source and destination accounts are required' };
        return {
            transactions: [{
                ...base,
                description,
                amount,
                type: 'Income',
                category: selectedTemplate.category || paymentAccount.name,
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
            type: isCreditPayment ? 'CreditExpense' : 'Expense',
            category,
            from_account_id: paymentAccount.id,
            to_account_id: expenseAccount.id,
        }],
    };
};
