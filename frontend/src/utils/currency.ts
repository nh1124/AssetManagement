const SYMBOLS: Record<string, string> = {
    JPY: "¥",
    USD: "$",
    EUR: "€",
    GBP: "£",
    CNY: "¥",
};

export function getCurrencySymbol(currency?: string) {
    return SYMBOLS[currency || "JPY"] || currency || "JPY";
}

const ZERO_DECIMAL_CURRENCIES = new Set(["JPY", "KRW"]);

export function formatCurrency(value: number | undefined | null, currency?: string) {
    const code = (currency || "JPY").toUpperCase();
    const symbol = getCurrencySymbol(code);
    const raw = value || 0;
    if (ZERO_DECIMAL_CURRENCIES.has(code)) {
        return `${symbol}${Math.round(raw).toLocaleString()}`;
    }
    return `${symbol}${(Math.round(raw * 100) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export function formatCompactCurrency(value: number | undefined | null, currency?: string) {
    const raw = Math.round(value || 0);
    const symbol = getCurrencySymbol(currency);
    return `${symbol}${raw.toLocaleString()}`;
}
