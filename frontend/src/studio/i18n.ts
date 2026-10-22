/* Two languages for the whole UI.
 *
 * Screens write their words inline as tr('日本語', 'English'); the shell's
 * shared words live in the dictionary below, keyed, because navigation.ts keeps
 * them as data. The active language is module state so that helpers outside
 * React (labels, exports, row builders) translate too: LanguageBoundary sets it
 * before its children render and remounts them when it changes, so a value
 * computed once on mount is never left in the old language.
 */
export type Language = 'ja' | 'en';

// The last language a signed-in client used, for the sign-in page and the first paint after reload.
export const LANGUAGE_STORAGE_KEY = 'ui.language';

function storedLanguage(): Language {
    try {
        return localStorage.getItem(LANGUAGE_STORAGE_KEY) === 'en' ? 'en' : 'ja';
    } catch {
        return 'ja';
    }
}

let active: Language = storedLanguage();

/** Only LanguageBoundary calls this, before its children render. */
export function setActiveLanguage(language: Language) {
    active = language;
}

/** The text in the active language. */
export function tr(ja: string, en: string): string {
    return active === 'en' ? en : ja;
}

export function activeLanguage(): Language {
    return active;
}

/** A label map for module scope: each read returns the active language's text. */
export function labels<K extends string>(pairs: Record<K, readonly [string, string]>): Record<K, string> {
    const result = {} as Record<K, string>;
    for (const key of Object.keys(pairs) as K[]) {
        Object.defineProperty(result, key, { get: () => tr(pairs[key][0], pairs[key][1]), enumerable: true });
    }
    return result;
}

/** Locale for Intl formatting in the active language. */
export function activeLocale(): string {
    return active === 'en' ? 'en-US' : 'ja-JP';
}

const dictionary = {
    'group.database': ['データベース', 'Database'],
    'group.automation': ['オートメーション', 'Automation'],
    'screen.ledger': ['家計簿', 'Ledger'],
    'screen.assets': ['資産', 'Assets'],
    'screen.flows': ['収支', 'Income & expenses'],
    'screen.plan': ['計画', 'Plan'],
    'screen.report': ['レポート', 'Reports'],
    'screen.goals': ['ゴール', 'Goals'],
    'screen.accounts': ['口座・勘定科目', 'Accounts'],
    'screen.fx': ['為替レート', 'Exchange rates'],
    'screen.autoTransactions': ['自動取引', 'Automatic transactions'],
    'screen.fixedAssets': ['固定資産', 'Fixed assets'],
    'screen.consumables': ['消耗品', 'Consumables'],
    'screen.earmarks': ['取り置き', 'Earmarks'],
    'screen.ai': ['AI操作', 'AI operations'],
    'screen.approvals': ['承認リクエスト', 'Approval requests'],
    'screen.audit': ['監査ログ', 'Audit log'],
    'tab.records': ['すべての記録', 'All records'],
    'tab.auto': ['自動取引', 'Automatic transactions'],
    'tab.overview': ['全体の状況', 'Overview'],
    'tab.accounts': ['口座', 'Accounts'],
    'tab.categories': ['分類別', 'By category'],
    'tab.subjects': ['科目', 'Accounts'],
    'tab.plan': ['計画と実績', 'Plan & actuals'],
    'tab.planEarmarks': ['取り置き', 'Earmarks'],
    'tab.planAuto': ['自動取引', 'Automatic'],
    'tab.trends': ['推移', 'Trends'],
    'tab.breakdown': ['内訳', 'Breakdown'],
    'tab.review': ['振り返り', 'Review'],
    'tab.export': ['出力', 'Export'],
    'tab.services': ['支出', 'Spending'],
    'tab.income': ['収入', 'Income'],
    'tab.repayment': ['返済', 'Repayment'],
    'tab.transfer': ['振替', 'Transfer'],
    'tab.allocation': ['配分', 'Allocation'],
    'shell.collapse': ['サイドバーを閉じる（Ctrl+\\）', 'Close sidebar (Ctrl+\\)'],
    'shell.expand': ['サイドバーを開く（Ctrl+\\）', 'Open sidebar (Ctrl+\\)'],
    'shell.home': ['ホームへ', 'Go home'],
    'shell.editTransaction': ['取引を編集', 'Edit transaction'],
    'shell.record': ['取引を記録', 'Record a transaction'],
    'shell.signOut': ['サインアウト', 'Sign out'],
    'common.loading': ['読み込んでいます…', 'Loading…'],
    'common.busy': ['処理中…', 'Working…'],
    'common.cancel': ['キャンセル', 'Cancel'],
    'settings.title': ['設定', 'Settings'],
    'settings.client': ['クライアント：{name}（#{id}）', 'Client: {name} (#{id})'],
    'settings.identifying': ['クライアントを確認しています…', 'Identifying the client…'],
    'settings.preferences': ['クライアントと表示設定', 'Client & display preferences'],
    'settings.currency': ['通貨', 'Currency'],
    'settings.timezone': ['タイムゾーン', 'Timezone'],
    'settings.browserZone': ['{zone}（ブラウザーの設定）', '{zone} (browser timezone)'],
    'settings.timezoneScope': ['日付・時刻の表示と、既定の日付・基準日として使う「今日」を変更します。記録した取引の日付はそのまま保持され、タイムゾーンを変更しても変換・書き換えは行いません。', 'Changes date and time display and what “today” means for default dates and as-of dates. Recorded transaction dates keep the date you gave them; changing the timezone never converts or rewrites them.'],
    'settings.language': ['言語', 'Language'],
    'settings.languageScope': ['画面全体と通知の言語です。口座名やメモなど、入力した内容は翻訳されません。', 'The language of every screen and of notifications. What you typed, such as account names and notes, is not translated.'],
    'settings.save': ['表示設定を保存', 'Save display preferences'],
    'settings.saved': ['表示設定を保存しました。', 'Display preferences saved.'],
    'settings.failed': ['操作に失敗しました。入力内容を確認して、もう一度お試しください。', 'The operation failed. Check your input and try again.'],
    'settings.mfaLoadFailed': ['MFAの状態を取得できませんでした。再読み込みしてください。', 'Could not load MFA status. Please reload.'],
    'settings.transfer': ['データの入出力', 'Data transfer'],
    'settings.export': ['データを書き出す（JSON）', 'Export data (JSON)'],
    'settings.exported': ['データのダウンロードを開始しました。', 'Data download started.'],
    'settings.file': ['読み込むバックアップファイル', 'Backup file to import'],
    'settings.selectedFile': ['選択したファイル：{name}', 'Selected file: {name}'],
    'settings.importScope': ['読み込みは、このクライアントの既存データをすべて置き換えます。', 'Import replaces all existing data for this client.'],
    'settings.import': ['データを読み込む', 'Import data'],
    'settings.imported': ['データを読み込みました。', 'Data imported.'],
    'settings.importConfirm': ['「{file}」を読み込みますか？\n「{name}」（クライアント #{id}）の既存データをすべて置き換えます。', 'Import “{file}”?\nThis replaces all existing data for “{name}” (client #{id}).'],
    'settings.invalidFile': ['データのバックアップを含むJSONファイルを選択してください。', 'Choose a valid JSON file containing a data backup.'],
    'account.title': ['アカウント', 'Account'],
    'account.name': ['名前', 'Name'],
    'account.email': ['メールアドレス', 'Email'],
    'account.newPassword': ['新しいパスワード（変更するときだけ）', 'New password (only to change it)'],
    'account.confirmPassword': ['新しいパスワード（確認）', 'Confirm new password'],
    'account.mismatch': ['新しいパスワードが一致しません。', 'The new passwords do not match.'],
    'account.help': ['メールアドレスとパスワードの変更には、現在のパスワードが必要です。パスワードは8文字以上です。', 'Changing the email or the password requires your current password. Passwords need at least 8 characters.'],
    'account.save': ['アカウントを保存', 'Save account'],
    'account.saved': ['アカウントを保存しました。', 'Account saved.'],
    'account.wrongPassword': ['現在のパスワードが正しくありません。', 'The current password is incorrect.'],
    'account.taken': ['この名前またはメールアドレスは使われています。', 'This name or email is already in use.'],
    'account.invalid': ['入力内容を確認してください（パスワードは8文字以上）。', 'Check your input (passwords need at least 8 characters).'],
    'mfa.password': ['現在のパスワード', 'Current password'],
} as const satisfies Record<string, readonly [string, string]>;

export type TranslationKey = keyof typeof dictionary;
type Parameters = Record<string, string | number>;

export function t(key: TranslationKey, parameters: Parameters = {}): string {
    return dictionary[key][active === 'en' ? 1 : 0].replace(/\{(\w+)\}/g, (match, name: string) => String(parameters[name] ?? match));
}

/** The active language, for components; LanguageBoundary remounts them when it changes. */
export function useLanguage() {
    return { language: active, t };
}
