from typing import List
import pandas as pd
from models.domain import Asset, LifeGoal
from services.mock_data import (
    generate_mock_assets, 
    generate_history_data, 
    generate_ideal_trajectory,
    generate_mock_goals,
    generate_mock_transactions
)

class FinanceService:
    def get_assets(self) -> List[Asset]:
        return generate_mock_assets()
    
    def get_assets_df(self) -> pd.DataFrame:
        assets = self.get_assets()
        return pd.DataFrame([a.model_dump() for a in assets])
    
    def get_total_value(self) -> float:
        return sum(a.value_jpy for a in self.get_assets())
    
    def get_history(self) -> pd.DataFrame:
        return generate_history_data()
    
    def get_ideal_trajectory(self) -> pd.DataFrame:
        return generate_ideal_trajectory()
    
    def get_goals(self) -> List[LifeGoal]:
        return generate_mock_goals()
    
    def get_transactions_summary(self) -> pd.DataFrame:
        return generate_mock_transactions()

    def get_budget_status(self):
        return {"used": 120000, "limit": 150000}

    def get_runway_months(self) -> int:
        return 24

    def get_goal_probability(self) -> int:
        return 82
