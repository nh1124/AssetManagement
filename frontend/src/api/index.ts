import axios from 'axios';
import type { TransactionWithPeriodClose } from './periodCloses';
import type {
    Account,
    AccountEarmark,
    AccountFlowAnalysis,
    AccountFlowGrain,
    AccountFlowTransactionPage,
    AutomaticDepreciationRecording,
    GeneratedTransaction,
    ScheduledTransactions,
    AiChangeRequest,
    AiAuditLog,
    AiExecutionSettings,
    AiOperationPolicy,
    AiOperationPolicyPayload,
    AnalysisSummary,
    CapsuleDrawdown,
    CapsuleDrawdownInput,
    CapsuleDrawdownResult,
    Capsule,
    CapsuleRule,
    CapsuleFundingSource,
    CapsuleFundingSourceInput,
    DataHealthResult,
    DepreciationMethod,
    DataRepairResult,
    ExchangeRate,
    FxTrackedCurrency,
    ExchangeRateAutoUpdateResult,
    LoginResult,
    GoalEarmarkLink,
    LifeEvent,
    LifeEventProgress,
    MonthlyAction,
    MfaRecoveryCodes,
    MfaSetupStart,
    MfaStatus,
    MonthlyReport,
    PeriodReview,
    NetWorthHistoryPoint,
    Product,
    AutoTransaction,
    AutoTransactionInput,
    ReviewActionCreate,
    Transaction,
    TransactionProposal,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:18100';

const api = axios.create({
    baseURL: API_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
});

// Interceptor to add Auth header. Client identity is resolved from the JWT.
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('finance_access_token');
    if (token) {
        config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
});

// Interceptor to handle 401 Unauthorized responses
api.interceptors.response.use(
    (response) => response,
    (error) => {
        const hadToken = Boolean(localStorage.getItem('finance_access_token'));
        const url = String(error.config?.url || '');
        // A wrong step-up code also answers 401; it must not sign the user out.
        const isAuthFlow = url.startsWith('/auth/login') || url.startsWith('/auth/mfa/login/verify') || url.startsWith('/auth/register') || url.startsWith('/auth/reauth');
        if (error.response?.status === 401 && hadToken && !isAuthFlow) {
            localStorage.removeItem('finance_access_token');
            localStorage.removeItem('finance_client_id');
            window.location.reload(); // Force App to re-evaluate auth status
        }
        return Promise.reject(error);
    }
);

// Auth endpoints
export const login = async (credentials: any): Promise<LoginResult> => {
    const response = await api.post('/auth/login', credentials);
    return response.data;
};

export const verifyMfaLogin = async (payload: { mfa_token: string; code?: string; recovery_code?: string }): Promise<LoginResult> => {
    const response = await api.post('/auth/mfa/login/verify', payload);
    return response.data;
};

export const register = async (userData: any) => {
    const response = await api.post('/auth/register', userData);
    return response.data;
};

// Changing the email or the password requires current_password.
export interface ProfileUpdate { name?: string; email?: string; password?: string; current_password?: string }

export const updateProfile = async (payload: ProfileUpdate) => (await api.patch('/auth/me', payload)).data;

export const getMe = async () => {
    const response = await api.get('/me');
    return response.data;
};

export const getMfaStatus = async (): Promise<MfaStatus> => {
    const response = await api.get('/auth/mfa/status');
    return response.data;
};

export const startMfaSetup = async (payload: { current_password: string }): Promise<MfaSetupStart> => {
    const response = await api.post('/auth/mfa/setup/start', payload);
    return response.data;
};

export const verifyMfaSetup = async (payload: { code: string }): Promise<MfaRecoveryCodes> => {
    const response = await api.post('/auth/mfa/setup/verify', payload);
    return response.data;
};

export const disableMfa = async (payload: { current_password?: string; code?: string; recovery_code?: string }) => {
    const response = await api.post('/auth/mfa/disable', payload);
    return response.data;
};

export const regenerateMfaRecoveryCodes = async (payload: { current_password?: string; code?: string; recovery_code?: string }): Promise<MfaRecoveryCodes> => {
    const response = await api.post('/auth/mfa/recovery-codes/regenerate', payload);
    return response.data;
};

export const reauth = async (payload: { code?: string; recovery_code?: string }) => {
    const response = await api.post('/auth/reauth', payload);
    return response.data;
};

export const getAiPolicies = async (): Promise<AiOperationPolicy[]> => {
    const response = await api.get('/ai/policies');
    return response.data;
};

export const updateAiPolicies = async (policies: AiOperationPolicyPayload[]): Promise<AiOperationPolicy[]> => {
    const response = await api.put('/ai/policies', policies);
    return response.data;
};

export const getAiExecutionSettings = async (): Promise<AiExecutionSettings> => {
    const response = await api.get('/ai/execution-settings');
    return response.data;
};

export const updateAiExecutionSettings = async (settings: AiExecutionSettings): Promise<AiExecutionSettings> => {
    const response = await api.put('/ai/execution-settings', settings);
    return response.data;
};

export const getAiAuditLogs = async (params?: { limit?: number; offset?: number }): Promise<AiAuditLog[]> => {
    const search = new URLSearchParams();
    if (params?.limit) search.set('limit', String(params.limit));
    if (params?.offset) search.set('offset', String(params.offset));
    const query = search.toString();
    const response = await api.get(`/ai/audit-logs${query ? `?${query}` : ''}`);
    return response.data;
};

export const getAiChangeRequests = async (params?: { status?: string; limit?: number; offset?: number }): Promise<AiChangeRequest[]> => {
    const search = new URLSearchParams();
    if (params?.status) search.set('status', params.status);
    if (params?.limit) search.set('limit', String(params.limit));
    if (params?.offset) search.set('offset', String(params.offset));
    const query = search.toString();
    const response = await api.get(`/ai/change-requests${query ? `?${query}` : ''}`);
    return response.data;
};

export const approveAiChangeRequest = async (id: number, payload?: { step_up_token?: string | null }): Promise<AiChangeRequest> => {
    const response = await api.post(`/ai/change-requests/${id}/approve`, payload ?? {});
    return response.data;
};

export const applyAiChangeRequest = async (id: number): Promise<AiChangeRequest> => {
    const response = await api.post(`/ai/change-requests/${id}/apply`);
    return response.data;
};

export const rejectAiChangeRequest = async (id: number): Promise<AiChangeRequest> => {
    const response = await api.post(`/ai/change-requests/${id}/reject`);
    return response.data;
};

export const refreshAiChangeRequestPreview = async (id: number): Promise<AiChangeRequest> => {
    const response = await api.post(`/ai/change-requests/${id}/refresh-preview`);
    return response.data;
};

// Analysis endpoints

export const getAnalysisSummary = async (): Promise<AnalysisSummary> => {
    const response = await api.get('/analysis/summary');
    return response.data;
};

export const getBalanceSheet = async (year?: number, month?: number, asOf?: string) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    if (asOf) params.append('as_of', asOf);
    const response = await api.get(`/analysis/balance-sheet?${params.toString()}`);
    return response.data;
};

export const getProfitLoss = async (year?: number, month?: number, startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response = await api.get(`/analysis/profit-loss?${params.toString()}`);
    return response.data;
};

export const getVarianceAnalysis = async (year?: number, month?: number, startDate?: string, endDate?: string, planId?: number | null) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    if (planId) params.append('plan_id', String(planId));
    const response = await api.get(`/analysis/variance?${params.toString()}`);
    return response.data;
};

export const getAccountFlows = async (params: {
    startDate: string;
    endDate: string;
    grain?: AccountFlowGrain;
    accountTypes?: string[];
    includeZero?: boolean;
}): Promise<AccountFlowAnalysis> => {
    const query = new URLSearchParams({
        start_date: params.startDate,
        end_date: params.endDate,
        grain: params.grain ?? 'month',
    });
    if (params.accountTypes?.length) query.append('account_types', params.accountTypes.join(','));
    if (params.includeZero) query.append('include_zero', 'true');
    const response = await api.get(`/analysis/account-flows?${query.toString()}`);
    return response.data;
};

export const getAccountFlowTransactions = async (params: {
    accountId: number;
    startDate: string;
    endDate: string;
    limit?: number;
    offset?: number;
}): Promise<AccountFlowTransactionPage> => {
    const query = new URLSearchParams({
        account_id: String(params.accountId),
        start_date: params.startDate,
        end_date: params.endDate,
        limit: String(params.limit ?? 100),
        offset: String(params.offset ?? 0),
    });
    const response = await api.get(`/analysis/account-transactions?${query.toString()}`);
    return response.data;
};

export const getNetWorthHistory = async (months: number = 36): Promise<NetWorthHistoryPoint[]> => {
    const response = await api.get('/analysis/net-worth-history', { params: { months } });
    return response.data;
};

export const getPeriodReview = async (startDate: string, endDate: string): Promise<PeriodReview> => {
    const response = await api.get('/period-reviews/', { params: { start_date: startDate, end_date: endDate } });
    return response.data;
};

export const listPeriodReviews = async (limit: number = 50): Promise<PeriodReview[]> => {
    const response = await api.get('/period-reviews/list', { params: { limit } });
    return response.data;
};

export const savePeriodReview = async (review: {
    start_date: string;
    end_date: string;
    label: string;
    reflection: string;
    next_actions: string;
}): Promise<PeriodReview> => {
    const response = await api.put('/period-reviews/', review);
    return response.data;
};

export const getMonthlyActions = async (sourcePeriod?: string): Promise<MonthlyAction[]> => {
    const response = await api.get('/actions/', { params: sourcePeriod ? { source_period: sourcePeriod } : undefined });
    return response.data;
};

export const createMonthlyAction = async (payload: ReviewActionCreate): Promise<MonthlyAction> => {
    const response = await api.post('/actions/', payload);
    return response.data;
};

export const updateMonthlyAction = async (id: number, payload: ReviewActionCreate): Promise<MonthlyAction> => {
    const response = await api.put(`/actions/${id}`, payload);
    return response.data;
};

export const deleteMonthlyAction = async (id: number): Promise<void> => {
    await api.delete(`/actions/${id}`);
};

export const processDueMonthlyActions = async (): Promise<{ processed: MonthlyAction[] }> => {
    const response = await api.post('/actions/process-due');
    return response.data;
};

export const applyReviewAction = async (id: number): Promise<MonthlyAction> => {
    const response = await api.post(`/actions/${id}/apply`);
    return response.data;
};

export const skipReviewAction = async (id: number): Promise<MonthlyAction> => {
    const response = await api.post(`/actions/${id}/skip`);
    return response.data;
};

// Accounts endpoints
export const getAccounts = async (accountType?: string, isActive?: boolean): Promise<Account[]> => {
    const params = new URLSearchParams();
    if (accountType) params.append('account_type', accountType);
    // Omission preserves the API's active-only default for existing callers.
    if (isActive !== undefined) params.append('is_active', String(isActive));
    const query = params.toString();
    const response = await api.get(`/accounts/${query ? `?${query}` : ''}`);
    return response.data;
};

export const getAccountEarmarks = async (accountId: number): Promise<AccountEarmark[]> => {
    const response = await api.get<AccountEarmark[]>(`/accounts/${accountId}/earmarks`);
    return response.data;
};

export const createAccount = async (account: {
    name: string;
    account_type: Account['account_type'];
    is_active?: boolean;
    balance?: number;
    liability_closing_day?: number | null;
    liability_payment_day?: number | null;
    liability_payment_month_offset?: number;
    liability_payment_policy?: Account['liability_payment_policy'];
    liability_minimum_payment?: number | null;
    liability_fixed_payment_amount?: number | null;
    liability_installment_months?: number | null;
    liability_revolving_rate?: number | null;
}): Promise<Account> => {
    const response = await api.post('/accounts/', account);
    return response.data;
};

export const updateAccount = async (id: number, data: {
    name?: string;
    liability_closing_day?: number | null;
    liability_payment_day?: number | null;
    liability_payment_month_offset?: number;
    liability_payment_policy?: Account['liability_payment_policy'];
    liability_minimum_payment?: number | null;
    liability_fixed_payment_amount?: number | null;
    liability_installment_months?: number | null;
    liability_revolving_rate?: number | null;
    is_active?: boolean;
}): Promise<Account> => {
    const response = await api.put(`/accounts/${id}`, data);
    return response.data;
};

// Transaction endpoints
export interface TransactionQuery {
    startDate?: string;
    endDate?: string;
    amountMin?: string;
    amountMax?: string;
    accountId?: string;
    q?: string;
    limit?: number;
    offset?: number;
}

const appendTransactionQuery = (params: URLSearchParams, query?: TransactionQuery) => {
    if (!query) return;
    if (query.startDate) params.append('start_date', query.startDate);
    if (query.endDate) params.append('end_date', query.endDate);
    if (query.amountMin) params.append('amount_min', query.amountMin);
    if (query.amountMax) params.append('amount_max', query.amountMax);
    if (query.accountId) params.append('account_id', query.accountId);
    if (query.q) params.append('q', query.q);
    if (query.limit) params.append('limit', String(query.limit));
    if (query.offset) params.append('offset', String(query.offset));
};

export const getTransactionsPage = async (
    query: TransactionQuery
): Promise<{ items: Transaction[]; total: number }> => {
    const params = new URLSearchParams({ paginated: 'true' });
    appendTransactionQuery(params, query);
    const response = await api.get(`/transactions/?${params.toString()}`);
    return response.data;
};

export const getTransaction = async (id: number): Promise<Transaction> => {
    const response = await api.get(`/transactions/${id}`);
    return response.data;
};

export const getTransactionProposals = async (params?: { status?: string; origin?: string }): Promise<TransactionProposal[]> => {
    const search = new URLSearchParams();
    if (params?.status) search.set('status', params.status);
    if (params?.origin) search.set('origin', params.origin);
    const query = search.toString();
    const response = await api.get(`/transactions/proposals${query ? `?${query}` : ''}`);
    return response.data;
};

export const approveTransactionProposal = async (id: number): Promise<Transaction> => {
    const response = await api.post(`/transactions/proposals/${id}/approve`);
    return response.data;
};

export const rejectTransactionProposal = async (id: number, note?: string): Promise<TransactionProposal> => {
    const response = await api.post(`/transactions/proposals/${id}/reject`, { note });
    return response.data;
};

export const createTransaction = async (transaction: Omit<Transaction, 'id'>): Promise<TransactionWithPeriodClose> => {
    const response = await api.post('/transactions/', transaction);
    return response.data;
};

export const updateTransaction = async (
    id: number,
    transaction: Partial<Omit<Transaction, 'id'>>
): Promise<TransactionWithPeriodClose> => {
    const response = await api.put(`/transactions/${id}`, transaction);
    return response.data;
};

export const deleteTransaction = async (id: number) => {
    const response = await api.delete(`/transactions/${id}`);
    return response.data;
};

// Life Events endpoints
// Without a scenario the server answers with the goal scenario's events.
export const getLifeEvents = async (scenarioId?: number): Promise<LifeEvent[]> => {
    const response = await api.get('/life-events/', { params: { scenario_id: scenarioId } });
    return response.data;
};

/** Events with their 実績管理の設定 and the funding it gives (the goal scenario by default). */
export const getLifeEventsWithProgress = async (scenarioId?: number): Promise<LifeEventProgress[]> => {
    const response = await api.get('/life-events/with-progress', { params: { scenario_id: scenarioId } });
    return response.data;
};

// A new event belongs to the scenario it is created in; an update never moves it.
export type GoalPayload = Pick<LifeEvent, 'direction' | 'account_id' | 'name' | 'target_amount' | 'target_date' | 'priority' | 'note' | 'condition_mode'>;

export const createGoal = async (event: Partial<GoalPayload> & Pick<GoalPayload, 'name' | 'target_amount' | 'target_date'> & { scenario_id: number }): Promise<LifeEvent> => {
    const response = await api.post('/life-events/', event);
    return response.data;
};

export const updateGoal = async (id: number, event: Partial<GoalPayload>): Promise<LifeEvent> => {
    const response = await api.put(`/life-events/${id}`, event);
    return response.data;
};

export const deleteGoal = async (id: number) => {
    const response = await api.delete(`/life-events/${id}`);
    return response.data;
};

/** Replace which earmarks count toward a goal event, with their shares in percent. */
export const setGoalEarmarks = async (id: number, rows: GoalEarmarkLink[]): Promise<GoalEarmarkLink[]> => {
    const response = await api.put(`/life-events/${id}/earmarks`, rows.map(({ capsule_id, share }) => ({ capsule_id, share })));
    return response.data;
};

// Budget Builder
export const getBudgetSummary = async (
    period?: string,
    options: { cash_flow_start_period?: string; cash_flow_months?: number; plan_id?: number; include_unset?: boolean } = {},
) => {
    const response = await api.get('/budget-plans/summary', {
        params: {
            period,
            plan_id: options.plan_id,
            cash_flow_start_period: options.cash_flow_start_period,
            cash_flow_months: options.cash_flow_months,
            include_unset: options.include_unset,
        },
    });
    return response.data;
};

export type MonthlyPlanLinePayload = {
    target_period: string;
    line_type: string;
    target_type: string;
    target_id?: number | null;
    account_id?: number | null;
    source_account_id?: number | null;
    name?: string | null;
    amount: number;
    source?: string;
    source_kind?: string;
    manual_override?: boolean;
    cash_treatment?: 'auto' | 'cash' | 'non_cash';
    is_active?: boolean;
    plan_id?: number | null;
};

export const createMonthlyPlanLines = async (lines: MonthlyPlanLinePayload[]) => {
    const response = await api.post('/budget-plans/lines', lines);
    return response.data;
};

export const updateMonthlyPlanLines = async (lines: Array<MonthlyPlanLinePayload & { id: number }>) => {
    const response = await api.put('/budget-plans/lines/batch', lines);
    return response.data;
};


export const deleteMonthlyPlanLine = async (id: number) => {
    const response = await api.delete(`/budget-plans/lines/${id}`);
    return response.data;
};

// Products/Inventory endpoints
export const getProducts = async (): Promise<Product[]> => {
    const response = await api.get('/products/');
    return response.data;
};

// A save that changes an earmark's amounts is refused (409) with the changes and a
// fingerprint; repeating it with that fingerprint confirms exactly those changes.
export interface ReserveChange {
    capsule_id: number; name: string;
    target_before: number; target_after: number; monthly_before: number; monthly_after: number;
}
export interface ReserveConfirmation { code: 'reserve_changes_unconfirmed'; fingerprint: string; changes: ReserveChange[] }

export const reserveConfirmation = (failure: unknown): ReserveConfirmation | null => {
    if (!axios.isAxiosError(failure) || failure.response?.status !== 409) return null;
    const detail = failure.response.data?.detail;
    return detail?.code === 'reserve_changes_unconfirmed' ? detail as ReserveConfirmation : null;
};

const reserveParams = (fingerprint?: string) => fingerprint ? { params: { reserve_fingerprint: fingerprint } } : undefined;

export const createProduct = async (product: any, reserveFingerprint?: string) => {
    const response = await api.post('/products/', product, reserveParams(reserveFingerprint));
    return response.data;
};

export const updateProduct = async (id: number, product: any, reserveFingerprint?: string) => {
    const response = await api.put(`/products/${id}`, product, reserveParams(reserveFingerprint));
    return response.data;
};

// One request for every asset's position, so a list does not ask per row.
export const getDepreciationSummary = async (): Promise<{
    items: Array<{
        product_id: number; name: string; purchase_price: number; current_value: number;
        total_depreciation: number; monthly_depreciation: number;
        method: DepreciationMethod; next_period: string | null; blocked_reason: string | null;
    }>;
    total_book_value: number; total_depreciation: number; monthly_expense: number;
}> => {
    const response = await api.get('/analysis/depreciation');
    return response.data;
};

export const deleteProduct = async (id: number, reserveFingerprint?: string) => {
    await api.delete(`/products/${id}`, reserveParams(reserveFingerprint));
};

export const getAutoTransactions = async (): Promise<AutoTransaction[]> => {
    const response = await api.get('/auto-transactions/');
    return response.data;
};

export const createAutoTransaction = async (entry: AutoTransactionInput) => {
    const response = await api.post('/auto-transactions/', entry);
    return response.data;
};

export const updateAutoTransaction = async (id: number, entry: AutoTransactionInput) => {
    const response = await api.put(`/auto-transactions/${id}`, entry);
    return response.data;
};

export const deleteAutoTransaction = async (id: number) => {
    await api.delete(`/auto-transactions/${id}`);
};

// Client management
export const getClients = async () => {
    const response = await api.get('/clients/');
    return response.data;
};

export const updateClientSettings = async (clientId: number, general_settings: Record<string, unknown>) => {
    const response = await api.put(`/clients/${clientId}/settings`, { general_settings });
    return response.data;
};

// Data transfer endpoints
export const exportData = async () => {
    const response = await api.get('/data/export');
    return response.data;
};

export const importData = async (payload: any) => {
    const response = await api.post('/data/import', payload);
    return response.data;
};

export const checkDataHealth = async (): Promise<DataHealthResult> => {
    const response = await api.get('/data/health');
    return response.data;
};

export const repairDataHealth = async (): Promise<DataRepairResult> => {
    const response = await api.post('/data/health/repair');
    return response.data;
};

// Exchange rates
export const getExchangeRates = async (): Promise<ExchangeRate[]> => {
    const response = await api.get('/exchange-rates/');
    return response.data;
};

export const getTrackedCurrencies = async (): Promise<FxTrackedCurrency[]> => {
    const response = await api.get('/exchange-rates/tracked');
    return response.data;
};

export const trackCurrency = async (currency: string): Promise<FxTrackedCurrency> => {
    const response = await api.post('/exchange-rates/tracked', { currency });
    return response.data;
};

export const untrackCurrency = async (currency: string) => {
    const response = await api.delete(`/exchange-rates/tracked/${currency}`);
    return response.data;
};

export const deleteExchangeRate = async (id: number) => {
    const response = await api.delete(`/exchange-rates/${id}`);
    return response.data;
};

export const autoUpdateExchangeRates = async (): Promise<ExchangeRateAutoUpdateResult> => {
    const response = await api.post('/exchange-rates/auto-update');
    return response.data;
};

export const getAutomaticDepreciation = async (): Promise<AutomaticDepreciationRecording[]> => {
    return (await api.get('/automatic-recordings/depreciation')).data;
};

export const getGeneratedTransactions = async (period: string): Promise<GeneratedTransaction[]> => {
    return (await api.get('/automatic-recordings/generated', { params: { period } })).data;
};

export const getScheduledTransactions = async (period: string): Promise<ScheduledTransactions> => {
    const response = await api.get('/automatic-recordings/scheduled', { params: { period } });
    return response.data;
};

export const processDueAutomaticRecordings = async () => {
    const response = await api.post('/automatic-recordings/process-due');
    return response.data;
};


// Capsules endpoints
export const recordCapsuleDrawdown = async (capsuleId: number, payload: CapsuleDrawdownInput): Promise<CapsuleDrawdownResult> => {
    const response = await api.post<CapsuleDrawdownResult>(`/capsules/${capsuleId}/drawdown`, payload);
    return response.data;
};

export const getCapsuleDrawdowns = async (capsuleId: number): Promise<CapsuleDrawdown[]> => {
    const response = await api.get<CapsuleDrawdown[]>(`/capsules/${capsuleId}/drawdowns`);
    return response.data;
};

export const getCapsules = async (skip = 0, limit = 100): Promise<Capsule[]> => {
    const response = await api.get('/capsules/', { params: { skip, limit } });
    return response.data;
};

export const getCapsuleFundingSources = async (capsuleId: number): Promise<CapsuleFundingSource[]> => {
    const response = await api.get<CapsuleFundingSource[]>(`/capsules/${capsuleId}/funding-sources`);
    return response.data;
};

export const updateCapsuleFundingSources = async (capsuleId: number, sources: CapsuleFundingSourceInput[]): Promise<CapsuleFundingSource[]> => {
    // PUT replaces the whole plan; any omitted funding source is removed.
    // Allowlist request fields because the server rejects response-only keys.
    const payload = sources.map(({ account_id, target_amount, max_share_bp, sort_order }) => ({
        account_id, target_amount, max_share_bp, sort_order,
    }));
    const response = await api.put<CapsuleFundingSource[]>(`/capsules/${capsuleId}/funding-sources`, payload);
    return response.data;
};

export const setCapsuleAccountClaim = async (capsuleId: number, payload: {
    account_id: number;
    target_amount: number;
}): Promise<{ status: 'ok' | 'unchanged'; claimed: number; difference: number }> => {
    const response = await api.post<{ status: 'ok' | 'unchanged'; claimed: number; difference: number }>(`/capsules/${capsuleId}/account-claim`, payload);
    return response.data;
};

export const contributeToCapsule = async (id: number, payload: {
    amount: number;
    from_account_id: number;
}): Promise<unknown> => {
    const response = await api.post(`/capsules/${id}/contribute`, payload);
    return response.data;
};

export type CapsulePayload = Pick<Capsule, 'name' | 'target_amount' | 'monthly_contribution' | 'capsule_type' | 'target_amount_source' | 'monthly_contribution_source'> & { auto_post?: boolean; account_id?: number | null };

export const createCapsule = async (capsule: CapsulePayload): Promise<Capsule> => {
    const response = await api.post('/capsules/', capsule);
    return response.data;
};

export const updateCapsule = async (id: number, capsule: Partial<CapsulePayload>): Promise<Capsule> => {
    const response = await api.put(`/capsules/${id}`, capsule);
    return response.data;
};

// Deleting a capsule removes the reservation and its rules. The account it
// was reserving into keeps its balance and history, and is named in the reply.
export const deleteCapsule = async (id: number): Promise<{
    message: string;
    capsule_id: number;
    capsule_name: string | null;
    rules_deleted: number;
    retained_account_id: number | null;
    retained_account_name: string | null;
}> => {
    const response = await api.delete(`/capsules/${id}`);
    return response.data;
};

export const getCapsuleRules = async (): Promise<CapsuleRule[]> => {
    const response = await api.get('/capsules/rules');
    return response.data;
};

export interface CapsuleReservation {
    proposal_id: number;
    capsule_id: number | null;
    capsule_name: string | null;
    amount: number;
    currency: string;
    status: string;
    posted_transaction_id: number | null;
}

// What amending or deleting an entry would withdraw. A posted reservation
// takes its transfer with it, so the caller asks before it changes the entry.
export const getCapsuleReservations = async (transactionId: number): Promise<CapsuleReservation[]> => {
    const response = await api.get(`/transactions/${transactionId}/capsule-reservations`);
    return response.data;
};

export const createCapsuleRule = async (rule: Omit<CapsuleRule, 'id' | 'created_at' | 'capsule_name' | 'source_account_name' | 'source_mode' | 'amount_type'> & { source_mode: string; amount_type: string }): Promise<CapsuleRule> => {
    const response = await api.post('/capsules/rules', rule);
    return response.data;
};

export const updateCapsuleRule = async (id: number, rule: Partial<Parameters<typeof createCapsuleRule>[0]>): Promise<CapsuleRule> => {
    const response = await api.put(`/capsules/rules/${id}`, rule);
    return response.data;
};

export const deleteCapsuleRule = async (id: number) => {
    const response = await api.delete(`/capsules/rules/${id}`);
    return response.data;
};

export const getMonthlyReport = async (year?: number, month?: number): Promise<MonthlyReport> => {
    const response = await api.get('/reports/monthly', { params: { year, month } });
    return response.data;
};

export const getPeriodReport = async (startDate: string, endDate: string): Promise<MonthlyReport> => {
    const response = await api.get('/reports/period', { params: { start_date: startDate, end_date: endDate } });
    return response.data;
};

export const applyMonthlyReportAction = async (
    period: string,
    proposalId: string
): Promise<{ status: string; action: MonthlyAction }> => {
    const response = await api.post(`/reports/${period}/actions/${proposalId}/apply`);
    return response.data;
};

export const applyPeriodReportAction = async (
    startDate: string,
    endDate: string,
    proposalId: string
): Promise<{ status: string; action: MonthlyAction }> => {
    const response = await api.post(`/reports/period/actions/${proposalId}/apply`, null, {
        params: { start_date: startDate, end_date: endDate },
    });
    return response.data;
};

// Budget Plans

export const copyPeriodFullReplace = async (payload: {
    source_period: string;
    target_period: string;
    plan_id?: number;
}): Promise<void> => {
    await api.post('/budget-plans/copy-period', payload);
};

export default api;
