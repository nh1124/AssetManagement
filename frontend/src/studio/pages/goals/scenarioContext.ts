import { useOutletContext } from 'react-router-dom';
import type { LifeScenario } from '../../../api/lifeScenarios';

export interface ScenarioContext {
    scenario: LifeScenario;
    reload: () => void;
}

/** The scenario every step inside ScenarioLayout works on. */
export function useScenario(): ScenarioContext {
    return useOutletContext<ScenarioContext>();
}
