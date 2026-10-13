import api from './index';
import type { Transaction } from '../types';

export interface PeriodClose {
    id: number;
    client_id: number;
    period: string;
    closed_at: string;
    note: string | null;
}

export interface TransactionWithPeriodClose extends Transaction {
    closed_period?: string | null;
}

export async function getPeriodCloses(): Promise<PeriodClose[]> {
    return (await api.get<PeriodClose[]>('/period-closes')).data;
}

export async function closePeriod(period: string, note: string): Promise<PeriodClose> {
    return (await api.post<PeriodClose>('/period-closes', { period, note: note.trim() || null })).data;
}

export async function reopenPeriod(period: string): Promise<void> {
    await api.delete(`/period-closes/${period}`);
}
