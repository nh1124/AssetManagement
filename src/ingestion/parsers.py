"""
CSV Parsers for various financial institutions and services.
Normalizes different CSV formats into a unified transaction schema.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, List, Dict, Any
import csv
import re

import pandas as pd


@dataclass
class ParsedTransaction:
    """Normalized transaction data from CSV parsing"""
    transaction_date: date
    amount: Decimal
    description: str
    category_hint: Optional[str] = None
    from_account: Optional[str] = None
    to_account: Optional[str] = None
    is_income: bool = False
    is_transfer: bool = False
    raw_data: Optional[Dict[str, Any]] = None


class BaseParser(ABC):
    """Abstract base class for CSV parsers"""
    
    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file"""
        pass
    
    @abstractmethod
    def parse(self, file_path: Path) -> List[ParsedTransaction]:
        """Parse the file and return normalized transactions"""
        pass
    
    @staticmethod
    def safe_decimal(value: Any) -> Optional[Decimal]:
        """Safely convert a value to Decimal"""
        if value is None or value == "" or pd.isna(value):
            return None
        try:
            # Remove commas and currency symbols
            if isinstance(value, str):
                value = re.sub(r'[¥$€£,\s]', '', value)
                # Handle negative in parentheses: (100) -> -100
                if value.startswith('(') and value.endswith(')'):
                    value = '-' + value[1:-1]
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    
    @staticmethod
    def parse_date(value: Any, formats: List[str] = None) -> Optional[date]:
        """Parse date from various formats"""
        if value is None or value == "" or pd.isna(value):
            return None
        
        if isinstance(value, (datetime, date)):
            return value if isinstance(value, date) else value.date()
        
        formats = formats or [
            "%Y/%m/%d",
            "%Y-%m-%d",
            "%Y年%m月%d日",
            "%m/%d/%Y",
            "%d/%m/%Y",
        ]
        
        value_str = str(value).strip()
        for fmt in formats:
            try:
                return datetime.strptime(value_str, fmt).date()
            except ValueError:
                continue
        return None


class MoneyForwardParser(BaseParser):
    """Parser for MoneyForward CSV exports"""
    
    # Expected column names (Japanese)
    EXPECTED_COLUMNS = ["日付", "内容", "金額（円）", "保有金融機関", "大項目", "中項目"]
    
    def can_parse(self, file_path: Path) -> bool:
        """Check if file appears to be MoneyForward format"""
        try:
            # Try different encodings
            for encoding in ['utf-8', 'shift_jis', 'cp932']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                        if header:
                            # Check for characteristic columns
                            header_str = ','.join(header)
                            if '日付' in header_str and ('金額' in header_str or '保有金融機関' in header_str):
                                return True
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass
        return False
    
    def parse(self, file_path: Path) -> List[ParsedTransaction]:
        """Parse MoneyForward CSV"""
        transactions = []
        
        # Detect encoding
        encoding = self._detect_encoding(file_path)
        
        df = pd.read_csv(file_path, encoding=encoding)
        
        # Map columns (handle variations)
        column_map = self._map_columns(df.columns.tolist())
        
        for _, row in df.iterrows():
            try:
                tx_date = self.parse_date(row.get(column_map.get('date', '日付')))
                if not tx_date:
                    continue
                
                amount = self.safe_decimal(row.get(column_map.get('amount', '金額（円）')))
                if amount is None:
                    continue
                
                description = str(row.get(column_map.get('description', '内容'), ''))
                category = str(row.get(column_map.get('category', '大項目'), ''))
                subcategory = str(row.get(column_map.get('subcategory', '中項目'), ''))
                account = str(row.get(column_map.get('account', '保有金融機関'), ''))
                
                # Determine if income or expense
                is_income = amount > 0 or category in ['収入', '給与', '賞与', 'その他入金']
                is_transfer = '振替' in category or '振替' in description
                
                transactions.append(ParsedTransaction(
                    transaction_date=tx_date,
                    amount=abs(amount),
                    description=description,
                    category_hint=f"{category}/{subcategory}" if subcategory else category,
                    from_account=account if not is_income else None,
                    to_account=account if is_income else None,
                    is_income=is_income,
                    is_transfer=is_transfer,
                    raw_data=row.to_dict(),
                ))
            except Exception as e:
                print(f"Warning: Failed to parse row: {e}")
                continue
        
        return transactions
    
    def _detect_encoding(self, file_path: Path) -> str:
        """Detect file encoding"""
        for encoding in ['utf-8', 'shift_jis', 'cp932', 'euc-jp']:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(1000)
                return encoding
            except UnicodeDecodeError:
                continue
        return 'utf-8'
    
    def _map_columns(self, columns: List[str]) -> Dict[str, str]:
        """Map expected column names to actual column names"""
        column_map = {}
        
        date_patterns = ['日付', 'date', '取引日']
        amount_patterns = ['金額', 'amount', '￥']
        desc_patterns = ['内容', '摘要', 'description', 'memo']
        category_patterns = ['大項目', 'category', 'カテゴリ']
        account_patterns = ['保有金融機関', 'account', '口座']
        
        for col in columns:
            col_lower = col.lower()
            if any(p in col_lower or p in col for p in date_patterns):
                column_map['date'] = col
            elif any(p in col_lower or p in col for p in amount_patterns):
                column_map['amount'] = col
            elif any(p in col_lower or p in col for p in desc_patterns):
                column_map['description'] = col
            elif any(p in col_lower or p in col for p in category_patterns):
                column_map['category'] = col
            elif any(p in col_lower or p in col for p in account_patterns):
                column_map['account'] = col
        
        return column_map


class GenericBankParser(BaseParser):
    """Generic parser for common bank CSV formats"""
    
    def can_parse(self, file_path: Path) -> bool:
        """Most generic parser - can try to parse any CSV"""
        return file_path.suffix.lower() == '.csv'
    
    def parse(self, file_path: Path) -> List[ParsedTransaction]:
        """Parse generic bank CSV"""
        transactions = []
        
        # Try different encodings
        for encoding in ['utf-8', 'shift_jis', 'cp932']:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                break
            except (UnicodeDecodeError, pd.errors.EmptyDataError):
                continue
        else:
            raise ValueError(f"Could not read file with any encoding: {file_path}")
        
        # Try to identify columns
        date_col = self._find_date_column(df)
        amount_col = self._find_amount_column(df)
        desc_col = self._find_description_column(df)
        
        if not date_col or not amount_col:
            raise ValueError("Could not identify required columns (date, amount)")
        
        for _, row in df.iterrows():
            try:
                tx_date = self.parse_date(row[date_col])
                if not tx_date:
                    continue
                
                amount = self.safe_decimal(row[amount_col])
                if amount is None:
                    continue
                
                description = str(row[desc_col]) if desc_col else ""
                
                transactions.append(ParsedTransaction(
                    transaction_date=tx_date,
                    amount=abs(amount),
                    description=description,
                    is_income=amount > 0,
                    raw_data=row.to_dict(),
                ))
            except Exception:
                continue
        
        return transactions
    
    def _find_date_column(self, df: pd.DataFrame) -> Optional[str]:
        """Find column containing dates"""
        date_keywords = ['date', 'day', '日付', '日', '取引日', '年月日']
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in date_keywords):
                return col
        
        # Try to find by content
        for col in df.columns:
            sample = df[col].dropna().head(5)
            for val in sample:
                if self.parse_date(val) is not None:
                    return col
        
        return None
    
    def _find_amount_column(self, df: pd.DataFrame) -> Optional[str]:
        """Find column containing amounts"""
        amount_keywords = ['amount', 'value', '金額', '￥', '円', 'price', '出金', '入金']
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in amount_keywords):
                return col
        
        return None
    
    def _find_description_column(self, df: pd.DataFrame) -> Optional[str]:
        """Find column containing descriptions"""
        desc_keywords = ['description', 'memo', '内容', '摘要', '備考', 'note', '取引内容']
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in desc_keywords):
                return col
        
        return None


class ParserFactory:
    """Factory for selecting appropriate parser based on file content"""
    
    _parsers = [
        MoneyForwardParser(),
        GenericBankParser(),  # Fallback parser
    ]
    
    @classmethod
    def get_parser(cls, file_path: Path) -> Optional[BaseParser]:
        """Get appropriate parser for the given file"""
        for parser in cls._parsers:
            if parser.can_parse(file_path):
                return parser
        return None
    
    @classmethod
    def register_parser(cls, parser: BaseParser, priority: int = 0) -> None:
        """Register a new parser with optional priority"""
        cls._parsers.insert(priority, parser)
