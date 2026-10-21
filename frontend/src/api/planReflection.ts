import api from './index';

/** 基準: the target over the months left, or the fixed amount the 積立設定 set when the earmark began. */
export type GoalBase = 'remaining' | 'goal_setting';
/** How what an earmark already holds comes off: evenly, or from the nearest months. */
export type HeldMode = 'even' | 'recent';
/** How a shortfall is caught up: evenly over the months, on this month, or not at all. */
export type CatchUp = 'even' | 'recent' | 'none';
export type ProductBase = 'remaining' | 'saved';

export interface ReflectionSettings {
    /** 自動反映: rewrite this month and the 11 after it at the start of a month and after a change. */
    enabled: boolean;
    goal: { base: GoalBase; held: HeldMode; catch_up: CatchUp };
    products: { enabled: boolean; base: ProductBase; held: HeldMode };
    /** The first month a shortfall of 積立 counts (the month the settings were first saved). */
    since: string | null;
    last_period: string | null;
}

export interface ReflectionPatch {
    enabled?: boolean;
    goal?: Partial<ReflectionSettings['goal']>;
    products?: Partial<ReflectionSettings['products']>;
}

/** One plan row a run writes, keeps or retires. */
export interface ReflectionChange {
    origin: 'goal' | 'products';
    period: string;
    kind: 'account' | 'transfer' | 'drawdown' | 'capsule';
    capsule_name: string | null;
    account_name: string | null;
    source_account_name: string | null;
    new_capsule: boolean;
    current: number;
    new: number;
    retire: boolean;
}

export type ReflectionTrigger = 'month' | 'change' | 'settings' | 'manual';

export interface ReflectionRun {
    id: number;
    applied_at: string | null;
    trigger: ReflectionTrigger;
    start_period: string;
    end_period: string;
    changes: number;
    rows: ReflectionChange[];
    warnings: string[];
    currency: string | null;
}

export interface ReflectionState {
    settings: ReflectionSettings;
    periods: string[];
    history: ReflectionRun[];
}

export interface ReflectionPreview {
    settings: ReflectionSettings;
    periods: string[];
    currency: string | null;
    scenario: { id: number; name: string } | null;
    changes: ReflectionChange[];
    warnings: string[];
}

export interface ReflectionResult {
    trigger: ReflectionTrigger;
    changes: number;
    periods: string[];
    warnings: string[];
}

export async function getReflection(): Promise<ReflectionState> {
    return (await api.get<ReflectionState>('/plan/reflection')).data;
}

export async function previewReflection(patch: ReflectionPatch = {}): Promise<ReflectionPreview> {
    return (await api.post<ReflectionPreview>('/plan/reflection/preview', patch)).data;
}

export async function saveReflectionSettings(patch: ReflectionPatch): Promise<{ settings: ReflectionSettings; run: ReflectionResult | null }> {
    return (await api.put<{ settings: ReflectionSettings; run: ReflectionResult | null }>('/plan/reflection/settings', patch)).data;
}

export async function runReflection(): Promise<ReflectionResult> {
    return (await api.post<ReflectionResult>('/plan/reflection/run')).data;
}
