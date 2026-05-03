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

export function formatCurrency(value: number | undefined | null, currency?: string) {
    return `${getCurrencySymbol(currency)}${Math.round(value || 0).toLocaleString()}`;
}

export function formatCompactCurrency(value: number | undefined | null, currency?: string) {
    const raw = Math.round(value || 0);
    const symbol = getCurrencySymbol(currency);
    if (Math.abs(raw) >= 100000000) return `${symbol}${(raw / 100000000).toFixed(1)}oku`;
    if (Math.abs(raw) >= 10000) return `${symbol}${(raw / 10000).toFixed(0)}man`;
    return `${symbol}${raw.toLocaleString()}`;
}
