import axios from 'axios';
import type { AnalysisSummary, Transaction } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8100';

const api = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

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

// Products endpoints
export const getProducts = async () => {
    const response = await api.get('/products/');
    return response.data;
};

export const createProduct = async (product: any) => {
    const response = await api.post('/products/', product);
    return response.data;
};

export default api;
