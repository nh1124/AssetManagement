import axios from 'axios';
import type {
    Account,
    AccountRole,
    AccountTreeNode,
    AnalysisSummary,
    MonthlyAction,
    MonteCarloResult,
    MonthlyBudget,
    MonthlyReport,
    MonthlyReview,
    Milestone,
    MilestoneSimulationPreview,
    MilestoneSimulationRequest,
    PeriodReview,
    NetWorthHistoryPoint,
    ReconcileResponse,
    RecurringTransaction,
    ReviewActionCreate,
    RoadmapProjection,
    Transaction,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:18100';

const api = axios.create({
    baseURL: API_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
});

// Interceptor to add Auth and X-Client-Id headers
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('finance_access_token');
    if (token) {
        config.headers['Authorization'] = `Bearer ${token}`;
    }
    const clientId = localStorage.getItem('finance_client_id') || '1';
    config.headers['X-Client-Id'] = clientId;
    return config;
});

// Interceptor to handle 401 Unauthorized responses
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            localStorage.removeItem('finance_access_token');
            // We don't necessarily want to remove client_id if we want to remember the last tenant,
            // but for security it's often better to clear it or let the user re-select/default to 1.
            window.location.reload(); // Force App to re-evaluate auth status
        }
        return Promise.reject(error);
    }
);


// Auth endpoints
export const login = async (credentials: any) => {
    const response = await api.post('/auth/login', credentials);
    return response.data;
};

export const register = async (userData: any) => {
    const response = await api.post('/auth/register', userData);
    return response.data;
};

export const updateProfile = async (profileData: any) => {

    const response = await api.patch('/auth/me', profileData);
    return response.data;
};

export const getMe = async () => {
    const response = await api.get('/me');
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

export const getProfitLoss = async (year?: number, month?: number, rollup: boolean = false, startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    if (rollup) params.append('rollup', 'true');
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response = await api.get(`/analysis/profit-loss?${params.toString()}`);
    return response.data;
};

export const getVarianceAnalysis = async (year?: number, month?: number, startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response = await api.get(`/analysis/variance?${params.toString()}`);
    return response.data;
};

export const getDepreciation = async () => {
    const response = await api.get('/analysis/depreciation');
    return response.data;
};

export const getNetWorthHistory = async (months: number = 36): Promise<NetWorthHistoryPoint[]> => {
    const response = await api.get('/analysis/net-worth-history', { params: { months } });
    return response.data;
};

export const getMonthlyReview = async (period?: string): Promise<MonthlyReview> => {
    const response = await api.get('/monthly-reviews/', { params: { period } });
    return response.data;
};

export const saveMonthlyReview = async (review: {
    target_period: string;
    reflection: string;
    next_actions: string;
}): Promise<MonthlyReview> => {
    const response = await api.put('/monthly-reviews/', review);
    return response.data;
};

export const getPeriodReview = async (startDate: string, endDate: string): Promise<PeriodReview> => {
    const response = await api.get('/period-reviews/', { params: { start_date: startDate, end_date: endDate } });
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
export const getAccounts = async (accountType?: string): Promise<Account[]> => {
    const params = accountType ? `?account_type=${accountType}` : '';
    const response = await api.get(`/accounts/${params}`);
    return response.data;
};

export const getAccountsByType = async () => {
    const response = await api.get('/accounts/by-type');
    return response.data;
};

export const getAccountTree = async (): Promise<Record<string, AccountTreeNode[]>> => {
    const response = await api.get('/accounts/tree');
    return response.data;
};

export const createAccount = async (account: {
    name: string;
    account_type: string;
    balance?: number;
    parent_id?: number | null;
    expected_return?: number;
    role?: AccountRole;
    role_target_amount?: number | null;
}): Promise<Account> => {
    const response = await api.post('/accounts/', account);
    return response.data;
};

export const updateAccount = async (id: number, data: {
    name?: string;
    parent_id?: number | null;
    expected_return?: number;
    role?: AccountRole;
    role_target_amount?: number | null;
    is_active?: boolean;
}): Promise<Account> => {
    const response = await api.put(`/accounts/${id}`, data);
    return response.data;
};

export const deleteAccount = async (id: number) => {
    const response = await api.delete(`/accounts/${id}`);
    return response.data;
};

export const seedDefaultAccounts = async () => {
    const response = await api.post('/accounts/seed-defaults');
    return response.data;
};

// Transaction endpoints
export interface TransactionQuery {
    startDate?: string;
    endDate?: string;
    type?: string;
    category?: string;
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
    if (query.type) params.append('type', query.type);
    if (query.category) params.append('category', query.category);
    if (query.amountMin) params.append('amount_min', query.amountMin);
    if (query.amountMax) params.append('amount_max', query.amountMax);
    if (query.accountId) params.append('account_id', query.accountId);
    if (query.q) params.append('q', query.q);
    if (query.limit) params.append('limit', String(query.limit));
    if (query.offset) params.append('offset', String(query.offset));
};

export const getTransactions = async (startDate?: string, endDate?: string): Promise<Transaction[]> => {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response = await api.get(`/transactions/?${params.toString()}`);
    return response.data;
};

export const getTransactionsPage = async (
    query: TransactionQuery
): Promise<{ items: Transaction[]; total: number }> => {
    const params = new URLSearchParams({ paginated: 'true' });
    appendTransactionQuery(params, query);
    const response = await api.get(`/transactions/?${params.toString()}`);
    return response.data;
};

export const createTransaction = async (transaction: Omit<Transaction, 'id'>): Promise<Transaction> => {
    const response = await api.post('/transactions/', transaction);
    return response.data;
};

export const updateTransaction = async (
    id: number,
    transaction: Partial<Omit<Transaction, 'id'>>
): Promise<Transaction> => {
    const response = await api.put(`/transactions/${id}`, transaction);
    return response.data;
};

export const deleteTransaction = async (id: number) => {
    const response = await api.delete(`/transactions/${id}`);
    return response.data;
};

// Life Events endpoints
export const getLifeEvents = async () => {
    const response = await api.get('/life-events/');
    return response.data;
};

export const getLifeEventsWithProgress = async () => {
    const response = await api.get('/life-events/with-progress');
    return response.data;
};

export const getGoalProbability = async () => {
    const response = await api.get('/life-events/goal-probability');
    return response.data;
};

export const getStrategyDashboard = async (annual_return: number = 5.0, inflation: number = 2.0, monthly_savings: number = 50000) => {
    const response = await api.get('/life-events/dashboard', {
        params: { annual_return, inflation, monthly_savings }
    });
    return response.data;
};

export const createLifeEvent = async (event: any) => {
    const response = await api.post('/life-events/', event);
    return response.data;
};

export const updateLifeEvent = async (id: number, event: any) => {
    const response = await api.put(`/life-events/${id}`, event);
    return response.data;
};

export const deleteLifeEvent = async (id: number) => {
    const response = await api.delete(`/life-events/${id}`);
    return response.data;
};

// Goal-domain aliases. Backend routes remain compatible with the original
// /life-events paths, while new UI code can depend on the Goal vocabulary.
export const getGoalDashboard = getStrategyDashboard;
export const createGoal = createLifeEvent;
export const updateGoal = updateLifeEvent;
export const deleteGoal = deleteLifeEvent;

// Goal Allocations
export const getAllocations = async (eventId: number) => {
    const response = await api.get(`/life-events/${eventId}/allocations`);
    return response.data;
};

export const addAllocation = async (eventId: number, allocation: { account_id: number; allocation_percentage: number }) => {
    const response = await api.post(`/life-events/${eventId}/allocations`, allocation);
    return response.data;
};

export const updateAllocation = async (allocationId: number, allocation: { account_id: number; allocation_percentage: number }) => {
    const response = await api.put(`/life-events/allocations/${allocationId}`, allocation);
    return response.data;
};

export const deleteAllocation = async (allocationId: number) => {
    const response = await api.delete(`/life-events/allocations/${allocationId}`);
    return response.data;
};

// Budget Builder
export const getBudgetSummary = async (period?: string) => {
    const response = await api.get('/life-events/budget-summary', { params: { period } });
    return response.data;
};

export const saveMonthlyBudgets = async (budgets: Array<{ account_id: number; target_period: string; amount: number }>) => {
    const response = await api.post('/life-events/monthly-budget/batch', budgets);
    return response.data;
};

export const updateAccountExpectedReturn = async (id: number, expected_return: number) => {
    const response = await api.put(`/accounts/${id}`, { expected_return });
    return response.data;
};

// Simulation endpoints
export const getSimulationConfig = async () => {
    const response = await api.get('/simulation/config');
    return response.data;
};

export const saveSimulationConfig = async (config: any) => {
    const response = await api.post('/simulation/config', config);
    return response.data;
};

export const runMonteCarloSimulation = async (lifeEventId: number, nSimulations: number = 1000): Promise<MonteCarloResult> => {
    const response = await api.post(`/simulation/monte-carlo/${lifeEventId}`, null, {
        params: { n_simulations: nSimulations }
    });
    return response.data;
};

// Budget endpoints
export const getBudgets = async (period?: string): Promise<MonthlyBudget[]> => {
    const response = await api.get('/budgets/', { params: { period } });
    return response.data;
};

export const createBudget = async (budget: { account_id: number; target_period: string; amount: number }) => {
    const response = await api.post('/budgets/', budget);
    return response.data;
};

export const deleteBudget = async (id: string) => {
    const response = await api.delete(`/budgets/${id}`);
    return response.data;
};

// Products/Inventory endpoints
export const getProducts = async () => {
    const response = await api.get('/products/');
    return response.data;
};

export const getUnitEconomicsSummary = async () => {
    const response = await api.get('/products/unit-economics-summary');
    return response.data;
};

export const createProduct = async (product: any) => {
    const response = await api.post('/products/', product);
    return response.data;
};

export const updateProduct = async (id: number, product: any) => {
    const response = await api.put(`/products/${id}`, product);
    return response.data;
};

export const deleteProduct = async (id: number) => {
    await api.delete(`/products/${id}`);
};

// AI/Analysis backend-side
export const analyzeWithBackend = async (payload: { parts: any[] }) => {
    const response = await api.post('/api/analyze/', payload);
    return response.data;
};

export const suggestBudget = async () => {
    const response = await api.post('/api/analyze/suggest-budget');
    return response.data;
};

export const optimizeAllocations = async () => {
    const response = await api.post('/api/analyze/optimize-allocations');
    return response.data;
};

// Client management
export const getClients = async () => {
    const response = await api.get('/clients/');
    return response.data;
};

export const updateClientKey = async (clientId: number, gemini_api_key: string) => {
    const response = await api.put(`/clients/${clientId}/key`, { gemini_api_key });
    return response.data;
};

export const updateClientSettings = async (clientId: number, general_settings: Record<string, unknown>) => {
    const response = await api.put(`/clients/${clientId}/settings`, { general_settings });
    return response.data;
};

export const createClient = async (payload: { name: string; seed_defaults: boolean }) => {
    const response = await api.post('/clients/', payload);
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

// Recurring Transactions endpoints
export const getRecurringTransactions = async (): Promise<RecurringTransaction[]> => {
    const response = await api.get('/recurring/');
    return response.data;
};

export const createRecurringTransaction = async (recurring: any) => {
    const response = await api.post('/recurring/', recurring);
    return response.data;
};

export const updateRecurringTransaction = async (id: number, data: any) => {
    const response = await api.put(`/recurring/${id}`, data);
    return response.data;
};

export const deleteRecurringTransaction = async (id: number) => {
    const response = await api.delete(`/recurring/${id}`);
    return response.data;
};

export const getDueRecurringTransactions = async (): Promise<RecurringTransaction[]> => {
    const response = await api.get('/recurring/due');
    return response.data;
};

export const processRecurringTransaction = async (id: number) => {
    const response = await api.post(`/recurring/${id}/process`);
    return response.data;
};

export const skipRecurringTransaction = async (id: number) => {
    const response = await api.post(`/recurring/${id}/skip`);
    return response.data;
};

// Roadmap endpoints
export const getRoadmapProjection = async (params: {
    years?: number;
    annual_return?: number;
    inflation?: number;
    monthly_savings?: number;
} = {}): Promise<RoadmapProjection> => {
    const response = await api.get('/roadmap/projection', { params });
    return response.data;
};

export const getMilestones = async (lifeEventId?: number): Promise<Milestone[]> => {
    const response = await api.get('/roadmap/milestones', {
        params: lifeEventId ? { life_event_id: lifeEventId } : undefined,
    });
    return response.data;
};

export const createMilestone = async (milestone: any): Promise<Milestone> => {
    const response = await api.post('/roadmap/milestones', milestone);
    return response.data;
};

export const deleteMilestone = async (id: number): Promise<Milestone> => {
    const response = await api.delete(`/roadmap/milestones/${id}`);
    return response.data;
};

export const resetMilestonesFromAnnualPlan = async (lifeEventId: number): Promise<Milestone[]> => {
    const response = await api.post(`/roadmap/life-events/${lifeEventId}/milestones/reset-from-annual`);
    return response.data;
};

export const previewMilestonesFromSimulation = async (
    lifeEventId: number,
    payload: MilestoneSimulationRequest
): Promise<MilestoneSimulationPreview> => {
    const response = await api.post(`/roadmap/life-events/${lifeEventId}/milestones/from-simulation/preview`, payload);
    return response.data;
};

export const applyMilestonesFromSimulation = async (
    lifeEventId: number,
    payload: MilestoneSimulationRequest
): Promise<Milestone[]> => {
    const response = await api.post(`/roadmap/life-events/${lifeEventId}/milestones/from-simulation`, payload);
    return response.data;
};

// Capsules endpoints
export const getCapsules = async () => {
    const response = await api.get('/capsules/');
    return response.data;
};

export const createCapsule = async (capsule: any) => {
    const response = await api.post('/capsules/', capsule);
    return response.data;
};

export const updateCapsule = async (id: number, capsule: any) => {
    const response = await api.put(`/capsules/${id}`, capsule);
    return response.data;
};

export const deleteCapsule = async (id: number) => {
    const response = await api.delete(`/capsules/${id}`);
    return response.data;
};

export const processCapsuleContributions = async () => {
    const response = await api.post('/capsules/process_contributions');
    return response.data;
};

export const contributeToCapsule = async (
    capsuleId: number,
    payload: { amount: number; from_account_id: number; contribution_date?: string }
) => {
    const response = await api.post(`/capsules/${capsuleId}/contribute`, payload);
    return response.data;
};

export const getReconcileStatus = async (): Promise<ReconcileResponse> => {
    const response = await api.get('/analysis/reconcile');
    return response.data;
};

export const fixReconcile = async (): Promise<ReconcileResponse> => {
    const response = await api.post('/analysis/reconcile/fix');
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

export default api;
