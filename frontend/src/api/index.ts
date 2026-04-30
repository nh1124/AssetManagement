import axios from 'axios';
import type {
    AnalysisSummary,
    MonteCarloResult,
    MonthlyBudget,
    MonthlyReview,
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

export const getBalanceSheet = async (year?: number, month?: number) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    const response = await api.get(`/analysis/balance-sheet?${params.toString()}`);
    return response.data;
};

export const getProfitLoss = async (year?: number, month?: number) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    const response = await api.get(`/analysis/profit-loss?${params.toString()}`);
    return response.data;
};

export const getVarianceAnalysis = async (year?: number, month?: number) => {
    const params = new URLSearchParams();
    if (year) params.append('year', String(year));
    if (month) params.append('month', String(month));
    const response = await api.get(`/analysis/variance?${params.toString()}`);
    return response.data;
};

export const getDepreciation = async () => {
    const response = await api.get('/analysis/depreciation');
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

// Accounts endpoints
export const getAccounts = async (accountType?: string) => {
    const params = accountType ? `?account_type=${accountType}` : '';
    const response = await api.get(`/accounts/${params}`);
    return response.data;
};

export const getAccountsByType = async () => {
    const response = await api.get('/accounts/by-type');
    return response.data;
};

export const createAccount = async (account: { name: string; account_type: string; balance?: number; budget_limit?: number; expected_return?: number }) => {
    const response = await api.post('/accounts/', account);
    return response.data;
};

export const updateAccount = async (id: number, data: { name?: string; budget_limit?: number; expected_return?: number; is_active?: boolean }) => {
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
export const getTransactions = async (startDate?: string, endDate?: string): Promise<Transaction[]> => {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response = await api.get(`/transactions/?${params.toString()}`);
    return response.data;
};

export const createTransaction = async (transaction: Omit<Transaction, 'id'>): Promise<Transaction> => {
    const response = await api.post('/transactions/', transaction);
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

export const getBudgetDefaults = async () => {
    const response = await api.get('/budgets/defaults');
    return response.data;
};

export const updateBudgetDefault = async (accountId: number, budget_limit: number | null) => {
    const response = await api.put(`/budgets/defaults/${accountId}`, { budget_limit });
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
export const getRecurringTransactions = async () => {
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

export const getDueRecurringTransactions = async () => {
    const response = await api.get('/recurring/due');
    return response.data;
};

export const processRecurringTransaction = async (id: number) => {
    const response = await api.post(`/recurring/${id}/process`);
    return response.data;
};

// Roadmap endpoints
export const getMilestones = async () => {
    const response = await api.get('/roadmap/milestones');
    return response.data;
};

export const createMilestone = async (milestone: any) => {
    const response = await api.post('/roadmap/milestones', milestone);
    return response.data;
};

export const deleteMilestone = async (id: number) => {
    const response = await api.delete(`/roadmap/milestones/${id}`);
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

export const getReconcileStatus = async () => {
    const response = await api.get('/analysis/reconcile');
    return response.data;
};

export const fixReconcile = async () => {
    const response = await api.post('/analysis/reconcile/fix');
    return response.data;
};

export const getMonthlyReport = async (year?: number, month?: number) => {
    const response = await api.get('/reports/monthly', { params: { year, month } });
    return response.data;
};

export const runPurchaseAudit = async (payload: {
    name: string;
    price: number;
    lifespan_months: number;
    category?: string;
}) => {
    const response = await api.post('/purchase-audit', payload);
    return response.data;
};

export default api;
