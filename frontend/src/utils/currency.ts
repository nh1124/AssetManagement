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
