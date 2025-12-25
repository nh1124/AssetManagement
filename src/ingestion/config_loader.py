"""
Configuration Loader Module
Loads YAML/Excel configuration files into the database.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import StandardCostParam, CostUnit


class ConfigLoader:
    """Loads configuration files into the database"""
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
    
    def load_standard_costs(self, file_path: Path) -> int:
        """
        Load standard costs from YAML file into database.
        
        Args:
            file_path: Path to standard_costs.yaml
        
        Returns:
            Number of cost parameters loaded/updated
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if not config:
            return 0
        
        count = 0
        with Session(self.engine) as session:
            for category_key, params in config.items():
                if not isinstance(params, dict):
                    continue
                
                unit_cost = Decimal(str(params.get('unit_cost', 0)))
                unit = params.get('unit', 'PER_MONTH')
                description = params.get('description', '')
                
                # Validate unit
                if unit not in [u.value for u in CostUnit]:
                    print(f"Warning: Invalid unit '{unit}' for {category_key}, defaulting to PER_MONTH")
                    unit = CostUnit.PER_MONTH.value
                
                # Upsert
                existing = session.query(StandardCostParam).filter_by(
                    category_key=category_key
                ).first()
                
                if existing:
                    existing.unit_cost = unit_cost
                    existing.unit = unit
                    existing.description = description
                    existing.updated_at = datetime.utcnow()
                    existing.source_file = str(file_path.name)
                else:
                    param = StandardCostParam(
                        category_key=category_key,
                        unit_cost=unit_cost,
                        unit=unit,
                        description=description,
                        source_file=str(file_path.name),
                    )
                    session.add(param)
                
                count += 1
            
            session.commit()
        
        print(f"✓ Loaded {count} standard cost parameters from {file_path.name}")
        return count
    
    def load_settings(self, file_path: Path) -> Dict[str, Any]:
        """
        Load general settings from YAML file.
        
        Args:
            file_path: Path to settings.yaml
        
        Returns:
            Dictionary of settings
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Settings file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f)
        
        return settings or {}
    
    def get_standard_costs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all standard costs from database.
        
        Returns:
            Dictionary of category_key -> {unit_cost, unit, description}
        """
        result = {}
        with Session(self.engine) as session:
            params = session.query(StandardCostParam).all()
            for param in params:
                result[param.category_key] = {
                    'unit_cost': float(param.unit_cost),
                    'unit': param.unit,
                    'description': param.description,
                }
        return result
    
    def calculate_monthly_cost(self, category_key: str) -> Optional[Decimal]:
        """
        Calculate monthly cost for a given category.
        
        Args:
            category_key: The category key to look up
        
        Returns:
            Monthly cost in JPY, or None if not found
        """
        with Session(self.engine) as session:
            param = session.query(StandardCostParam).filter_by(
                category_key=category_key
            ).first()
            
            if not param:
                return None
            
            if param.unit == CostUnit.PER_DAY.value:
                return param.unit_cost * 30
            elif param.unit == CostUnit.PER_MONTH.value:
                return param.unit_cost
            elif param.unit == CostUnit.PER_YEAR.value:
                return param.unit_cost / 12
            
            return param.unit_cost
    
    def get_total_monthly_cost(self) -> Decimal:
        """
        Calculate total monthly living cost from all standard cost parameters.
        
        Returns:
            Total monthly cost in JPY
        """
        total = Decimal('0')
        with Session(self.engine) as session:
            params = session.query(StandardCostParam).all()
            for param in params:
                if param.unit == CostUnit.PER_DAY.value:
                    total += param.unit_cost * 30
                elif param.unit == CostUnit.PER_MONTH.value:
                    total += param.unit_cost
                elif param.unit == CostUnit.PER_YEAR.value:
                    total += param.unit_cost / 12
        
        return total


def load_all_configs(db_url: str, config_dir: Path) -> Dict[str, Any]:
    """
    Convenience function to load all configuration files.
    
    Args:
        db_url: SQLAlchemy database URL
        config_dir: Directory containing config files
    
    Returns:
        Dictionary with loaded settings
    """
    loader = ConfigLoader(db_url)
    result = {}
    
    # Load standard costs
    costs_file = config_dir / "standard_costs.yaml"
    if costs_file.exists():
        count = loader.load_standard_costs(costs_file)
        result['standard_costs_count'] = count
    
    # Load settings
    settings_file = config_dir / "settings.yaml"
    if settings_file.exists():
        result['settings'] = loader.load_settings(settings_file)
    
    return result
