"""
UI Components
Reusable Streamlit components for various pages.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import (
    Account,
    AssetPosition,
    LifeGoal,
    Transaction,
    AssetClass,
    Priority,
)
from core.valuation import ValuationEngine
from core.depreciation import DepreciationEngine
from ingestion.importer import DataImporter
from ingestion.config_loader import ConfigLoader
from strategy.auditor import PurchaseAuditor, AuditDecision


def render_sidebar():
    """Render sidebar navigation"""
    # Already implemented in main.py
    pass


def render_assets_page(db_url: str):
    """Render assets management page"""
    st.header("💼 Assets Management")
    
    engine = create_engine(db_url)
    valuation = ValuationEngine(db_url)
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["📋 All Assets", "➕ Add Asset", "📊 Analysis"])
    
    with tab1:
        try:
            portfolio = valuation.valuate_portfolio()
            
            if portfolio.positions:
                # Summary
                st.metric("Total Portfolio Value", f"¥{portfolio.total_net_value_jpy:,.0f}")
                
                # Asset table
                data = []
                for pos in portfolio.positions:
                    data.append({
                        "Name": pos.name,
                        "Ticker": pos.ticker,
                        "Class": pos.asset_class,
                        "Quantity": float(pos.quantity),
                        "Unit Price": float(pos.unit_price_jpy),
                        "Value (JPY)": float(pos.valuation_jpy),
                        "Gain/Loss": float(pos.unrealized_gain_jpy),
                    })
                
                st.dataframe(data, use_container_width=True)
            else:
                st.info("No assets registered. Add your first asset below.")
        except Exception as e:
            st.warning(f"Could not load assets: {e}")
    
    with tab2:
        st.subheader("Register New Asset")
        
        with st.form("add_asset"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Asset Name", placeholder="MacBook Pro 2024")
                ticker = st.text_input("Ticker/ID", placeholder="MACBOOK_2024 or AAPL")
                
                with Session(engine) as session:
                    classes = session.query(AssetClass).all()
                    class_options = {c.name: c.code for c in classes}
                
                asset_class = st.selectbox("Asset Class", options=list(class_options.keys()))
            
            with col2:
                quantity = st.number_input("Quantity", min_value=1, value=1)
                acquisition_price = st.number_input("Acquisition Price (JPY)", min_value=0, value=100000)
                acquisition_date = st.date_input("Acquisition Date", value=date.today())
            
            # Optional for durable goods
            st.markdown("**For Durable Assets (optional)**")
            col1, col2 = st.columns(2)
            with col1:
                lifespan_years = st.number_input("Lifespan (years)", min_value=0.0, value=0.0, step=0.5)
            with col2:
                salvage_value = st.number_input("Salvage Value (JPY)", min_value=0, value=0)
            
            submitted = st.form_submit_button("Add Asset", type="primary")
            
            if submitted and name:
                try:
                    with Session(engine) as session:
                        # Get or create default account
                        account = session.query(Account).first()
                        if not account:
                            account = Account(name="Default Account")
                            session.add(account)
                            session.flush()
                        
                        pos = AssetPosition(
                            account_id=account.id,
                            asset_class_code=class_options[asset_class],
                            ticker_symbol=ticker or name.upper().replace(' ', '_'),
                            name=name,
                            quantity=Decimal(str(quantity)),
                            acquisition_price=Decimal(str(acquisition_price)),
                            acquisition_date=acquisition_date,
                            lifespan_days=int(lifespan_years * 365) if lifespan_years > 0 else None,
                            salvage_value=Decimal(str(salvage_value)) if salvage_value > 0 else None,
                        )
                        session.add(pos)
                        session.commit()
                    
                    st.success(f"✅ Added asset: {name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding asset: {e}")
    
    with tab3:
        st.subheader("Asset Analysis")
        
        depreciation = DepreciationEngine(db_url)
        dep_summary = depreciation.calculate_depreciation()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Total Acquisition Value", f"¥{dep_summary.total_acquisition_value:,.0f}")
            st.metric("Current Book Value", f"¥{dep_summary.total_current_book_value:,.0f}")
        
        with col2:
            st.metric("Accumulated Depreciation", f"¥{dep_summary.total_accumulated_depreciation:,.0f}")
            st.metric("Monthly Depreciation", f"¥{dep_summary.monthly_depreciation_expense:,.0f}")


def render_goals_page(db_url: str):
    """Render goals management page"""
    st.header("🎯 Life Goals")
    
    engine = create_engine(db_url)
    
    # Tabs
    tab1, tab2 = st.tabs(["📋 My Goals", "➕ Add Goal"])
    
    with tab1:
        with Session(engine) as session:
            goals = session.query(LifeGoal).all()
            
            if goals:
                for goal in goals:
                    with st.expander(f"**{goal.name}** - ¥{goal.target_amount:,.0f}", expanded=True):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Target Date:** {goal.target_date}")
                        with col2:
                            st.write(f"**Priority:** {goal.priority}")
                        with col3:
                            days_left = (goal.target_date - date.today()).days
                            st.write(f"**Days Left:** {days_left}")
                        
                        if goal.description:
                            st.write(goal.description)
                        
                        # Delete button
                        if st.button(f"🗑️ Delete", key=f"del_{goal.id}"):
                            session.delete(goal)
                            session.commit()
                            st.rerun()
            else:
                st.info("No goals set. Create your first financial goal!")
    
    with tab2:
        st.subheader("Create New Goal")
        
        with st.form("add_goal"):
            name = st.text_input("Goal Name", placeholder="老後資金")
            target_amount = st.number_input("Target Amount (JPY)", min_value=0, value=20000000)
            target_date = st.date_input("Target Date", value=date(date.today().year + 20, 12, 31))
            priority = st.selectbox("Priority", options=[p.value for p in Priority])
            description = st.text_area("Description (optional)")
            
            submitted = st.form_submit_button("Create Goal", type="primary")
            
            if submitted and name:
                try:
                    with Session(engine) as session:
                        goal = LifeGoal(
                            name=name,
                            target_amount=Decimal(str(target_amount)),
                            target_date=target_date,
                            priority=priority,
                            description=description if description else None,
                        )
                        session.add(goal)
                        session.commit()
                    
                    st.success(f"✅ Created goal: {name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error creating goal: {e}")


def render_import_page(db_url: str):
    """Render data import page"""
    st.header("📥 Data Import")
    
    tab1, tab2 = st.tabs(["📄 CSV Import", "⚙️ Config Import"])
    
    with tab1:
        st.subheader("Import Transaction CSV")
        
        uploaded_file = st.file_uploader(
            "Upload CSV file",
            type=['csv'],
            help="Supports MoneyForward and generic bank CSV formats"
        )
        
        account_name = st.text_input("Account Name", placeholder="A銀行 普通預金")
        
        if uploaded_file and st.button("Import", type="primary"):
            # Save uploaded file temporarily
            import_dir = Path("data/raw_csv")
            import_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = import_dir / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Import
            importer = DataImporter(db_url)
            result = importer.import_file(file_path, account_name or None)
            
            if result.errors:
                st.warning(f"Import completed with errors: {len(result.errors)}")
                for err in result.errors[:5]:
                    st.error(err)
            else:
                st.success(f"""
                ✅ Import Complete!
                - Total rows: {result.total_rows}
                - Imported: {result.imported_rows}
                - Duplicates skipped: {result.duplicate_rows}
                """)
    
    with tab2:
        st.subheader("Load Configuration")
        
        config_dir = Path("config")
        
        if st.button("Load Standard Costs"):
            try:
                loader = ConfigLoader(db_url)
                count = loader.load_standard_costs(config_dir / "standard_costs.yaml")
                st.success(f"✅ Loaded {count} standard cost parameters")
            except Exception as e:
                st.error(f"Error loading config: {e}")
        
        st.markdown("---")
        st.subheader("Current Standard Costs")
        
        try:
            loader = ConfigLoader(db_url)
            costs = loader.get_standard_costs()
            
            if costs:
                data = [
                    {
                        "Category": k,
                        "Unit Cost": f"¥{v['unit_cost']:,.0f}",
                        "Unit": v['unit'],
                        "Description": v.get('description', ''),
                    }
                    for k, v in costs.items()
                ]
                st.dataframe(data, use_container_width=True)
                
                total_monthly = loader.get_total_monthly_cost()
                st.metric("Total Monthly Living Cost", f"¥{total_monthly:,.0f}")
            else:
                st.info("No standard costs configured. Click 'Load Standard Costs' above.")
        except Exception as e:
            st.warning(f"Could not load costs: {e}")


def render_audit_page(db_url: str):
    """Render purchase audit page"""
    st.header("🔍 Smart Purchase Audit")
    st.markdown("高額購入の意思決定を支援します（資産計上基準: ¥30,000以上）")
    
    auditor = PurchaseAuditor(db_url)
    
    with st.form("audit_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            item_name = st.text_input("商品名", placeholder="MacBook Pro 14インチ")
            price = st.number_input("購入価格 (JPY)", min_value=0, value=250000)
            lifespan = st.number_input("想定耐用年数", min_value=0.5, value=5.0, step=0.5)
        
        with col2:
            resale = st.number_input("想定売却価格 (JPY)", min_value=0, value=25000)
            liquid_assets = st.number_input("現在の流動資産 (JPY)", min_value=0, value=3000000)
            monthly_expenses = st.number_input("月次支出 (JPY)", min_value=0, value=200000)
        
        submitted = st.form_submit_button("🔍 Analyze Purchase", type="primary")
    
    if submitted and item_name:
        result = auditor.audit_purchase(
            item_name=item_name,
            price=Decimal(str(price)),
            lifespan_years=lifespan,
            resale_value=Decimal(str(resale)),
            current_liquid_assets=Decimal(str(liquid_assets)),
            monthly_expenses=Decimal(str(monthly_expenses)),
        )
        
        st.markdown("---")
        
        # Decision banner
        if result.decision == AuditDecision.GO:
            st.success(f"✅ **GO** - {result.decision_reason}")
        elif result.decision == AuditDecision.WAIT:
            st.warning(f"⏸️ **WAIT** - {result.decision_reason}")
        else:
            st.error(f"🛑 **STOP** - {result.decision_reason}")
        
        # Cost Analysis
        st.subheader("💰 Cost Analysis")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Daily Cost", f"¥{result.daily_cost:,.0f}")
        with col2:
            st.metric("Monthly Cost", f"¥{result.monthly_cost:,.0f}")
        with col3:
            st.metric("Annual Cost", f"¥{result.annual_cost:,.0f}")
        with col4:
            st.metric("True Cost", f"¥{result.true_cost:,.0f}")
        
        # Impact Analysis
        st.subheader("📊 Impact Analysis")
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Runway Impact", f"-{result.runway_impact_months:.1f} months")
        with col2:
            st.metric("Asset Life Impact", f"{result.asset_life_impact_days} days of savings")
        
        # Trade-offs
        if result.trade_offs:
            st.subheader("⚖️ Goal Trade-offs")
            for tradeoff in result.trade_offs:
                st.warning(f"**{tradeoff.goal_name}**: {tradeoff.impact_description}")
        
        # Alternatives
        st.subheader("💡 Alternatives")
        for alt in result.alternative_suggestions:
            st.info(f"• {alt}")


def render_settings_page(db_url: str):
    """Render settings page"""
    st.header("⚙️ Settings")
    
    tab1, tab2, tab3 = st.tabs(["🏦 Accounts", "📊 Database", "ℹ️ About"])
    
    with tab1:
        st.subheader("Manage Accounts")
        
        engine = create_engine(db_url)
        
        with Session(engine) as session:
            accounts = session.query(Account).all()
            
            if accounts:
                for acc in accounts:
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.write(f"**{acc.name}** ({acc.tax_type})")
                    with col2:
                        st.write(acc.institution or "-")
        
        st.markdown("---")
        st.subheader("Add Account")
        
        with st.form("add_account"):
            name = st.text_input("Account Name")
            institution = st.text_input("Institution (optional)")
            tax_type = st.selectbox("Tax Type", options=["TAXABLE", "NISA", "IDECO", "CASH"])
            
            if st.form_submit_button("Add Account"):
                if name:
                    with Session(engine) as session:
                        acc = Account(name=name, institution=institution, tax_type=tax_type)
                        session.add(acc)
                        session.commit()
                    st.success(f"Added account: {name}")
                    st.rerun()
    
    with tab2:
        st.subheader("Database Information")
        st.code(f"Database URL: {db_url}")
        
        if st.button("Initialize Database"):
            try:
                import subprocess
                subprocess.run(["python", "scripts/db_init.py"], check=True)
                st.success("Database initialized!")
            except Exception as e:
                st.error(f"Error: {e}")
        
        if st.button("Reset Database", type="secondary"):
            st.warning("⚠️ This will delete all data!")
            if st.button("Confirm Reset"):
                # Would implement reset logic
                pass
    
    with tab3:
        st.subheader("About")
        st.markdown("""
        ### 次世代金融資産管理システム v2.0
        
        **Python-Native & Local-First**
        
        このシステムは以下の機能を提供します:
        - 📊 資産の統合管理 (B/S生成)
        - 💰 キャッシュフロー分析
        - 🎯 ゴールベース運用
        - 📈 モンテカルロシミュレーション
        - 🔍 購買意思決定支援
        
        ---
        
        Built with ❤️ using:
        - Python 3.11
        - Streamlit
        - SQLAlchemy
        - Plotly
        """)
