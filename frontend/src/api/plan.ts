import api from './index';
import type { ScheduledTransaction } from '../types';

export type PlanRecordSection = 'allocation' | 'drawdown' | 'expense' | 'income' | 'debt_payment' | 'borrowing';
export type PlanRecordOrigin = 'goal' | 'registry' | 'card' | 'manual';

/** One record behind a section's budget, with where it comes from; only the user's are editable here. */
export interface PlanRecord {
    id: number | null;
    name: string;
    amount: number;
    origin: PlanRecordOrigin;
    origin_label: string;
    /** On a user's 返済 record for a card: the statement estimate the record stands in for. */
    card_estimate: number | null;
    editable: boolean;
    source_account_id: number | null;
}

export interface PlanSection {
    key: PlanRecordSection;
    label: string;
    /** The account's kind does not normally take this section (an automatic transaction's kind or account to check). */
    mismatch: boolean;
    total: number;
    actual: number;
    records: PlanRecord[];
    can_add: boolean;
}

/** An account's month on the plan page: its sections and the automatic transactions on it. */
export interface AccountMonth {
    account: { id: number; name: string; kind: 'asset' | 'liability' | 'income' | 'expense' };
    period: string;
    currency: string;
    sections: PlanSection[];
    /** Earmarks funded from this account this month: budgeted on their own rows, shown for reference. */
    earmarks: Array<{ capsule_id: number | null; name: string; amount: number; goal: boolean }>;
    scheduled: ScheduledTransaction[];
}

export async function getAccountMonth(period: string, accountId: number): Promise<AccountMonth> {
    return (await api.get<AccountMonth>(`/plan/${period}/accounts/${accountId}`)).data;
}

/** 自動扱い: the record becomes an automatic transaction; records_transactions also posts it on its day. */
export interface PlanAutomatic {
    frequency: 'Monthly' | 'Yearly';
    day_of_month: number;
    start_period: string;
    end_period: string | null;
    counter_account_id: number | null;
    records_transactions: boolean;
}

export async function addPlanRecord(payload: { period: string; account_id: number; section: PlanRecordSection; amount: number; name?: string; automatic?: PlanAutomatic }): Promise<AccountMonth> {
    return (await api.post<AccountMonth>('/plan/records', payload)).data;
}

export async function amendPlanRecord(id: number, payload: { amount: number; name?: string }): Promise<AccountMonth> {
    return (await api.put<AccountMonth>(`/plan/records/${id}`, payload)).data;
}

export async function deletePlanRecord(id: number): Promise<AccountMonth> {
    return (await api.delete<AccountMonth>(`/plan/records/${id}`)).data;
}
