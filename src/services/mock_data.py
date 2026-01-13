import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List
from models.domain import Asset, AssetCategory, LifeGoal

def generate_mock_assets() -> List[Asset]:
    """Generates a list of mock assets totaling 5M-10M JPY."""
    return [
        Asset(id="1", name="三菱UFJ銀行", category=AssetCategory.CASH, value_jpy=2500000.0, acquisition_date=datetime(2020, 1, 1).date()),
        Asset(id="2", name="eMAXIS Slim 米国株式", category=AssetCategory.STOCK, value_jpy=4000000.0, acquisition_date=datetime(2021, 5, 12).date(), ticker="S&P500"),
        Asset(id="3", name="eMAXIS Slim 全世界株式", category=AssetCategory.STOCK, value_jpy=2000000.0, acquisition_date=datetime(2021, 6, 15).date(), ticker="All-Country"),
        Asset(id="4", name="Bitcoin", category=AssetCategory.CRYPTO, value_jpy=1200000.0, acquisition_date=datetime(2022, 11, 20).date(), ticker="BTC"),
        Asset(id="5", name="Ethereum", category=AssetCategory.CRYPTO, value_jpy=300000.0, acquisition_date=datetime(2023, 1, 10).date(), ticker="ETH"),
    ]

def generate_history_data(days: int = 3 * 365) -> pd.DataFrame:
    """Generates daily asset value history for the last 3 years with volatility."""
    dates = [datetime.now().date() - timedelta(days=x) for x in range(days)]
    dates.reverse()
    
    # Starting value
    current_value = 5000000.0
    values = []
    
    np.random.seed(42)
    # 5% annual drift, 15% volatility
    daily_return = 0.05 / 365
    daily_vol = 0.15 / np.sqrt(365)
    
    for _ in range(days):
        change = np.random.normal(daily_return, daily_vol)
        current_value *= (1 + change)
        values.append(current_value)
        
    return pd.DataFrame({"date": dates, "value": values})

def generate_ideal_trajectory(days: int = 3 * 365) -> pd.DataFrame:
    """Generates a smooth ideal trajectory for comparison."""
    dates = [datetime.now().date() - timedelta(days=x) for x in range(days)]
    dates.reverse()
    
    start_value = 5000000.0
    annual_growth = 0.04
    values = [start_value * (1 + annual_growth)**(i/365) for i in range(days)]
    
    return pd.DataFrame({"date": dates, "ideal_value": values})

def generate_mock_goals() -> List[LifeGoal]:
    """Generates mock life goals."""
    return [
        LifeGoal(id="g1", name="House Purchase", target_amount=5000000.0, target_date=datetime.now().date() + timedelta(days=5*365), current_progress=0.4),
        LifeGoal(id="g2", name="Retirement Fund", target_amount=50000000.0, target_date=datetime.now().date() + timedelta(days=30*365), current_progress=0.2),
    ]

def generate_mock_transactions() -> pd.DataFrame:
    """Generates mock transaction data for P/L."""
    data = {
        "Month": ["2023-10", "2023-11", "2023-12", "2024-01"],
        "Income": [400000, 420000, 650000, 400000],
        "Expenses": [250000, 280000, 450000, 220000],
    }
    df = pd.DataFrame(data)
    df["Net P/L"] = df["Income"] - df["Expenses"]
    return df
