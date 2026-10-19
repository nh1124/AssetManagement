import type { ExchangeRate } from '../../../types';

// Stored inverse quotes remain usable after the tracking migration.
export function currencyHistory(rates: ExchangeRate[], currency: string, target: string): ExchangeRate[] {
    return rates.flatMap((row) => row.base_currency === currency && row.quote_currency === target ? [row]
        : row.quote_currency === currency && row.base_currency === target ? [{ ...row, base_currency: currency, quote_currency: target, rate: 1 / row.rate }] : [])
        .sort((a, b) => b.as_of_date.localeCompare(a.as_of_date) || b.id - a.id);
}
