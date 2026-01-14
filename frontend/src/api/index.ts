import axios from 'axios';
import type { AnalysisSummary, Transaction } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8100';

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

export const createAccount = async (account: { name: string; account_type: string; budget_limit?: number }) => {
    const response = await api.post('/accounts/', account);
    return response.data;
};

export const updateAccount = async (id: number, data: { name?: string; budget_limit?: number; is_active?: boolean }) => {
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

export const createLifeEvent = async (event: any) => {
    const response = await api.post('/life-events/', event);
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

// Budget endpoints
export const getBudgets = async (month?: string) => {
    const params = month ? `?month=${month}` : '';
    const response = await api.get(`/budgets/${params}`);
    return response.data;
};

export const createBudget = async (budget: any) => {
    const response = await api.post('/budgets/', budget);
    return response.data;
};

// Products/Inventory endpoints
export const getProducts = async () => {
    const response = await api.get('/products/');
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

// AI/Analysis backend-side
export const analyzeWithBackend = async (payload: { parts: any[] }) => {
    const response = await api.post('/api/analyze/', payload);
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

export default api;
