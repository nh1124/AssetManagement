// ============================================================
// Types for Asset Management MCP Server
// ============================================================

export interface Investment {
  type: string;
  account: string;
  monthly_amount: number;
  fund?: string;
  expense_ratio?: number;
  payment_method?: string;
  role: string;
  notes: string;
  // 持株会 specific
  effective_monthly?: number;
  bonus_rate?: number;
  stock?: string;
  // NISA specific
  lifetime_cap?: number;
  annual_cap?: number;
}

export interface EmergencyFund {
  target: number;
  current: number;
  monthly_contribution: number;
  target_date: string;
  account: string;
}

export interface PortfolioSummary {
  total_monthly_investment: number;
  total_monthly_allocation: number;
  us_equity_ratio: number;
}

export interface Profile {
  name: string;
  age: number;
  employer: string;
  joined_date: string;
  take_home: number;
}

export interface Portfolio {
  as_of: string;
  profile: Profile;
  investments: {
    nisa: Investment;
    dc: Investment;
    holdings: Investment;
  };
  emergency_fund: EmergencyFund;
  summary: PortfolioSummary;
}

export interface BudgetItem {
  category: string;
  planned: number;
  actual: number | null;
  min?: number;
  max?: number;
  notes?: string;
}

export interface Budget {
  as_of: string;
  phase: number;
  take_home: number;
  items: BudgetItem[];
}

export interface Decision {
  id: string;
  date: string;
  category: "nisa" | "dc" | "holdings" | "budget" | "strategy" | "other";
  title: string;
  description: string;
  rationale: string;
  outcome?: string;
}

export interface DecisionLog {
  decisions: Decision[];
}

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
  projections: {
    account: string;
    monthly_amount: number;
    annual_rate_pct: number;
    future_value: number;
  }[];
  total_future_value: number;
}
