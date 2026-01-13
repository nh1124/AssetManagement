import axios from 'axios';
import type { AnalysisSummary, Transaction } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_BASE_URL,
});

export const getAnalysisSummary = async (): Promise<AnalysisSummary> => {
    const response = await api.get('/analysis/summary');
    return response.data;
};

export const getTransactions = async (): Promise<Transaction[]> => {
    const response = await api.get('/transactions/');
    return response.data;
};

export const createTransaction = async (transaction: Omit<Transaction, 'id'>): Promise<Transaction> => {
    const response = await api.post('/transactions/', transaction);
    return response.data;
};

export default api;
