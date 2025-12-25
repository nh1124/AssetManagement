#!/usr/bin/env python3
"""
Database Initialization Script
Creates SQLite database with all tables and seeds initial master data.

Usage:
    python scripts/db_init.py [--test]
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import (
    Base,
    AssetClass,
    Currency,
    TransactionCategory,
)


def get_database_url(test: bool = False) -> str:
    """Get database URL based on mode"""
    if test:
        return "sqlite:///:memory:"
    
    # Ensure data directory exists
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    db_path = data_dir / "assets.db"
    return f"sqlite:///{db_path}"


def seed_asset_classes(session: Session) -> None:
    """Seed initial asset class master data"""
    asset_classes = [
        AssetClass(
            code="CASH",
            name="現金・預金",
            is_depreciable=False,
            is_market_linked=False,
        ),
        AssetClass(
            code="STOCK",
            name="株式",
            is_depreciable=False,
            is_market_linked=True,
        ),
        AssetClass(
            code="BOND",
            name="債券",
            is_depreciable=False,
            is_market_linked=True,
        ),
        AssetClass(
            code="FUND",
            name="投資信託",
            is_depreciable=False,
            is_market_linked=True,
        ),
        AssetClass(
            code="CRYPTO",
            name="暗号資産",
            is_depreciable=False,
            is_market_linked=True,
        ),
        AssetClass(
            code="DURABLE",
            name="耐久消費財",
            is_depreciable=True,
            is_market_linked=False,
        ),
        AssetClass(
            code="REAL_ESTATE",
            name="不動産",
            is_depreciable=True,
            is_market_linked=True,
        ),
    ]
    
    for ac in asset_classes:
        existing = session.query(AssetClass).filter_by(code=ac.code).first()
        if not existing:
            session.add(ac)
    
    session.commit()
    print(f"✓ Seeded {len(asset_classes)} asset classes")


def seed_currencies(session: Session) -> None:
    """Seed initial currency master data"""
    currencies = [
        Currency(code="JPY", symbol="¥", name="日本円"),
        Currency(code="USD", symbol="$", name="米ドル"),
        Currency(code="EUR", symbol="€", name="ユーロ"),
        Currency(code="GBP", symbol="£", name="英ポンド"),
    ]
    
    for curr in currencies:
        existing = session.query(Currency).filter_by(code=curr.code).first()
        if not existing:
            session.add(curr)
    
    session.commit()
    print(f"✓ Seeded {len(currencies)} currencies")


def seed_transaction_categories(session: Session) -> None:
    """Seed initial transaction category master data"""
    categories = [
        # Essential (基礎生活費)
        TransactionCategory(id=1, name="食費", is_essential=True),
        TransactionCategory(id=2, name="住居費", is_essential=True),
        TransactionCategory(id=3, name="光熱費", is_essential=True),
        TransactionCategory(id=4, name="通信費", is_essential=True),
        TransactionCategory(id=5, name="交通費", is_essential=True),
        TransactionCategory(id=6, name="医療費", is_essential=True),
        TransactionCategory(id=7, name="保険", is_essential=True),
        # Discretionary (変動費)
        TransactionCategory(id=10, name="日用品", is_essential=False),
        TransactionCategory(id=11, name="衣服・美容", is_essential=False),
        TransactionCategory(id=12, name="趣味・娯楽", is_essential=False),
        TransactionCategory(id=13, name="交際費", is_essential=False),
        TransactionCategory(id=14, name="教育・教養", is_essential=False),
        TransactionCategory(id=15, name="旅行", is_essential=False),
        # Special
        TransactionCategory(id=20, name="収入", is_essential=False),
        TransactionCategory(id=21, name="投資", is_essential=False),
        TransactionCategory(id=22, name="その他", is_essential=False),
    ]
    
    for cat in categories:
        existing = session.query(TransactionCategory).filter_by(id=cat.id).first()
        if not existing:
            session.add(cat)
    
    session.commit()
    print(f"✓ Seeded {len(categories)} transaction categories")


def init_database(test: bool = False) -> None:
    """Initialize database with tables and seed data"""
    db_url = get_database_url(test)
    print(f"Initializing database: {db_url}")
    
    engine = create_engine(db_url, echo=False)
    
    # Create all tables
    Base.metadata.create_all(engine)
    print("✓ Created all tables")
    
    # Seed master data
    with Session(engine) as session:
        seed_asset_classes(session)
        seed_currencies(session)
        seed_transaction_categories(session)
    
    print("\n✅ Database initialization complete!")
    
    if test:
        # Run basic verification for test mode
        print("\n--- Test Mode Verification ---")
        with Session(engine) as session:
            ac_count = session.query(AssetClass).count()
            curr_count = session.query(Currency).count()
            cat_count = session.query(TransactionCategory).count()
            print(f"  Asset Classes: {ac_count}")
            print(f"  Currencies: {curr_count}")
            print(f"  Transaction Categories: {cat_count}")
        print("--- Verification Complete ---")


def main():
    parser = argparse.ArgumentParser(description="Initialize Asset Management Database")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use in-memory database for testing",
    )
    args = parser.parse_args()
    
    init_database(test=args.test)


if __name__ == "__main__":
    main()
