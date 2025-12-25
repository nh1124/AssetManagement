"""
Data Importer Module
Handles the import of transactions from CSV files to the database.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import (
    Account,
    Transaction,
    TransactionType,
    TransactionCategory,
)
from .parsers import ParserFactory, ParsedTransaction


@dataclass
class ImportResult:
    """Result of a data import operation"""
    file_path: str
    total_rows: int
    imported_rows: int
    skipped_rows: int
    duplicate_rows: int
    error_rows: int
    errors: List[str]


class DataImporter:
    """Handles importing transaction data from CSV files"""
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
        self._category_cache: Dict[str, int] = {}
        self._account_cache: Dict[str, int] = {}
    
    def import_file(self, file_path: Path, account_name: Optional[str] = None) -> ImportResult:
        """
        Import a single CSV file.
        
        Args:
            file_path: Path to the CSV file
            account_name: Optional account name to associate transactions with
        
        Returns:
            ImportResult with statistics about the import
        """
        result = ImportResult(
            file_path=str(file_path),
            total_rows=0,
            imported_rows=0,
            skipped_rows=0,
            duplicate_rows=0,
            error_rows=0,
            errors=[],
        )
        
        # Get appropriate parser
        parser = ParserFactory.get_parser(file_path)
        if not parser:
            result.errors.append(f"No parser found for file: {file_path}")
            return result
        
        # Parse the file
        try:
            transactions = parser.parse(file_path)
            result.total_rows = len(transactions)
        except Exception as e:
            result.errors.append(f"Failed to parse file: {e}")
            return result
        
        # Import transactions
        with Session(self.engine) as session:
            self._load_caches(session)
            
            # Ensure account exists if specified
            account_id = None
            if account_name:
                account_id = self._get_or_create_account(session, account_name)
            
            for tx in transactions:
                try:
                    # Check for duplicates
                    tx_hash = self._transaction_hash(tx)
                    if self._is_duplicate(session, tx, tx_hash):
                        result.duplicate_rows += 1
                        continue
                    
                    # Determine transaction type
                    tx_type = self._determine_type(tx)
                    
                    # Find category
                    category_id = self._match_category(session, tx.category_hint) if tx.category_hint else None
                    
                    # Determine account
                    from_account_id = account_id
                    to_account_id = None
                    
                    if tx.from_account and tx.from_account != account_name:
                        from_account_id = self._get_or_create_account(session, tx.from_account)
                    if tx.to_account:
                        to_account_id = self._get_or_create_account(session, tx.to_account)
                    
                    if tx.is_income:
                        from_account_id, to_account_id = to_account_id, from_account_id or account_id
                    
                    # Create transaction record
                    db_tx = Transaction(
                        transaction_date=tx.transaction_date,
                        type=tx_type.value,
                        from_account_id=from_account_id,
                        to_account_id=to_account_id,
                        amount=tx.amount,
                        currency_code="JPY",
                        description=tx.description[:500] if tx.description else None,
                        category_id=category_id,
                        is_logical_only=False,
                    )
                    session.add(db_tx)
                    result.imported_rows += 1
                    
                except Exception as e:
                    result.error_rows += 1
                    result.errors.append(f"Row error: {e}")
            
            session.commit()
        
        result.skipped_rows = result.total_rows - result.imported_rows - result.duplicate_rows - result.error_rows
        return result
    
    def import_directory(self, dir_path: Path, pattern: str = "*.csv") -> List[ImportResult]:
        """Import all matching files from a directory"""
        results = []
        for file_path in dir_path.glob(pattern):
            result = self.import_file(file_path)
            results.append(result)
        return results
    
    def _load_caches(self, session: Session) -> None:
        """Load category and account caches"""
        # Load categories
        categories = session.query(TransactionCategory).all()
        self._category_cache = {cat.name: cat.id for cat in categories}
        
        # Load accounts
        accounts = session.query(Account).all()
        self._account_cache = {acc.name: acc.id for acc in accounts}
    
    def _get_or_create_account(self, session: Session, name: str) -> int:
        """Get existing account or create new one"""
        if name in self._account_cache:
            return self._account_cache[name]
        
        account = Account(name=name)
        session.add(account)
        session.flush()
        self._account_cache[name] = account.id
        return account.id
    
    def _determine_type(self, tx: ParsedTransaction) -> TransactionType:
        """Determine transaction type from parsed data"""
        if tx.is_transfer:
            return TransactionType.TRANSFER
        if tx.is_income:
            return TransactionType.INCOME
        return TransactionType.EXPENSE
    
    def _match_category(self, session: Session, category_hint: str) -> Optional[int]:
        """Match category hint to existing category"""
        if not category_hint:
            return None
        
        # Direct match
        if category_hint in self._category_cache:
            return self._category_cache[category_hint]
        
        # Try partial match
        hint_lower = category_hint.lower()
        for cat_name, cat_id in self._category_cache.items():
            if cat_name.lower() in hint_lower or hint_lower in cat_name.lower():
                return cat_id
        
        # Common mappings
        mappings = {
            '食費': '食費',
            '食料品': '食費',
            '住居': '住居費',
            '家賃': '住居費',
            '水道': '光熱費',
            '電気': '光熱費',
            'ガス': '光熱費',
            '通信': '通信費',
            '携帯': '通信費',
            '交通': '交通費',
            '電車': '交通費',
            '医療': '医療費',
            '病院': '医療費',
            '保険': '保険',
            '日用品': '日用品',
            '衣服': '衣服・美容',
            '美容': '衣服・美容',
            '趣味': '趣味・娯楽',
            '娯楽': '趣味・娯楽',
            '交際': '交際費',
            '教育': '教育・教養',
            '旅行': '旅行',
            '給与': '収入',
            '賞与': '収入',
            '投資': '投資',
        }
        
        for keyword, cat_name in mappings.items():
            if keyword in hint_lower:
                return self._category_cache.get(cat_name)
        
        return self._category_cache.get('その他')
    
    def _transaction_hash(self, tx: ParsedTransaction) -> str:
        """Generate a hash for duplicate detection"""
        content = f"{tx.transaction_date}|{tx.amount}|{tx.description}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _is_duplicate(self, session: Session, tx: ParsedTransaction, tx_hash: str) -> bool:
        """Check if transaction already exists"""
        existing = session.query(Transaction).filter(
            Transaction.transaction_date == tx.transaction_date,
            Transaction.amount == tx.amount,
            Transaction.description == tx.description[:500] if tx.description else None,
        ).first()
        return existing is not None


def import_csv_files(db_url: str, source_dir: Path) -> List[ImportResult]:
    """
    Convenience function to import all CSV files from a directory.
    
    Args:
        db_url: SQLAlchemy database URL
        source_dir: Directory containing CSV files
    
    Returns:
        List of ImportResult for each file
    """
    importer = DataImporter(db_url)
    return importer.import_directory(source_dir)
