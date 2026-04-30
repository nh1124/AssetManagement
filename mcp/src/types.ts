export interface FutureValueResult {
  monthly_amount: number;
  annual_rate_pct: number;
  years: number;
  future_value: number;
  total_contributed: number;
  total_gain: number;
  gain_ratio_pct: number;
}

export interface ProjectionResult {
  target_age: number;
  years_remaining: number;
  projections: Array<{ account: string; monthly_amount: number; annual_rate_pct: number; future_value: number }>;
  total_future_value: number;
}
