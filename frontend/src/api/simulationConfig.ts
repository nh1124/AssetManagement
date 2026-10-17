import api from './index';

export interface SimulationConfigInput {
    horizon_years: number;
    annual_return: number;
    tax_rate: number;
    is_nisa: boolean;
    monthly_savings: number;
    volatility: number;
    inflation_rate: number;
}

export interface SimulationConfig extends SimulationConfigInput {
    id: number;
}

export async function getSimulationConfig(): Promise<SimulationConfig> {
    return (await api.get<SimulationConfig>('/simulation/config')).data;
}

export async function putSimulationConfig(config: SimulationConfigInput): Promise<SimulationConfig> {
    return (await api.put<SimulationConfig>('/simulation/config', config)).data;
}
