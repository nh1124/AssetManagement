from pydantic import BaseModel
from datetime import date
from typing import Optional, List
from .models import TransactionType

class AssetBase(BaseModel):
    name: str
    category: str
    value: float

class AssetCreate(AssetBase):
    pass

class Asset(AssetBase):
    id: int

    class Config:
        from_attributes = True

class LiabilityBase(BaseModel):
    name: str
    category: str
    balance: float

class LiabilityCreate(LiabilityBase):
    pass

class Liability(LiabilityBase):
    id: int

    class Config:
        from_attributes = True

class TransactionBase(BaseModel):
    date: date
    description: str
    amount: float
    type: str
    asset_id: Optional[int] = None
    liability_id: Optional[int] = None

class TransactionCreate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: int

    class Config:
        from_attributes = True

class LifeEventBase(BaseModel):
    name: str
    target_date: date
    target_amount: float

class LifeEventCreate(LifeEventBase):
    pass

class LifeEvent(LifeEventBase):
    id: int

    class Config:
        from_attributes = True

class AnalysisSummary(BaseModel):
    net_worth: float
    monthly_pl: float
    liability_total: float
