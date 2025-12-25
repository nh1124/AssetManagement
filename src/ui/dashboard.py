"""
Dashboard Page
Main dashboard with KPIs, charts, and overview.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from decimal import Decimal

from core.valuation import ValuationEngine
from core.analyzer import CashFlowAnalyzer
from core.depreciation import DepreciationEngine
from strategy.simulator import SimulationEngine


def render_dashboard(db_url: str):
    """Render the main dashboard page"""
    
    st.markdown('<h1 class="main-header">💰 Asset Management Dashboard</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Financial snapshot as of today</p>', unsafe_allow_html=True)
    
    # Initialize engines
    try:
        valuation = ValuationEngine(db_url)
        analyzer = CashFlowAnalyzer(db_url)
        depreciation = DepreciationEngine(db_url)
        simulator = SimulationEngine(db_url)
    except Exception as e:
        st.warning(f"⚠️ Database not initialized. Please run `python scripts/db_init.py` first.")
        st.code(f"Error: {e}")
        return
    
    # Get data
    try:
        portfolio = valuation.valuate_portfolio()
        cash_flow = analyzer.analyze_cash_flow(months=6)
        dep_summary = depreciation.calculate_depreciation()
    except Exception as e:
        st.info("📊 No data available yet. Import transactions to see your dashboard.")
        _render_empty_dashboard()
        return
    
    # KPI Row
    st.subheader("📈 Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="Total Net Worth",
            value=f"¥{portfolio.total_net_value_jpy:,.0f}",
            delta=None,  # Would need historical data
        )
    
    with col2:
        st.metric(
            label="Savings Rate",
            value=f"{cash_flow.average_savings_rate:.1f}%",
            delta="Target: 20%",
        )
    
    with col3:
        runway = analyzer.analyze_burn_rate(portfolio.total_net_value_jpy)
        st.metric(
            label="Runway",
            value=f"{runway.runway_months} months",
            delta="🟢 Healthy" if runway.is_sustainable else "🔴 At Risk",
        )
    
    with col4:
        st.metric(
            label="Monthly Depreciation",
            value=f"¥{dep_summary.monthly_depreciation_expense:,.0f}",
            help="Hidden cost of asset ownership",
        )
    
    st.markdown("---")
    
    # Charts Row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🥧 Asset Allocation")
        if portfolio.by_asset_class:
            fig = px.pie(
                names=list(portfolio.by_asset_class.keys()),
                values=[float(v) for v in portfolio.by_asset_class.values()],
                title="By Asset Class",
                hole=0.4,
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No assets registered yet")
    
    with col2:
        st.subheader("📊 Cash Flow Trend")
        if cash_flow.monthly_flows:
            months = [f"{f.year}/{f.month:02d}" for f in cash_flow.monthly_flows]
            income = [float(f.income) for f in cash_flow.monthly_flows]
            expenses = [float(f.total_expenses) for f in cash_flow.monthly_flows]
            
            fig = go.Figure()
            fig.add_trace(go.Bar(name='Income', x=months, y=income, marker_color='#10b981'))
            fig.add_trace(go.Bar(name='Expenses', x=months, y=expenses, marker_color='#ef4444'))
            fig.update_layout(barmode='group', title='Income vs Expenses')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No transaction data available")
    
    st.markdown("---")
    
    # Goals Progress
    st.subheader("🎯 Goal Progress")
    
    try:
        sim_result = simulator.run_simulation(portfolio.total_net_value_jpy)
        
        if sim_result.goal_results:
            for goal in sim_result.goal_results:
                col1, col2 = st.columns([3, 1])
                with col1:
                    progress = min(float(goal.current_allocation / goal.target_amount) * 100, 100)
                    st.progress(progress / 100, text=f"{goal.goal_name}: {progress:.1f}%")
                with col2:
                    prob_color = "🟢" if goal.success_probability >= 85 else "🟡" if goal.success_probability >= 70 else "🔴"
                    st.write(f"{prob_color} {goal.success_probability:.0f}% 確率")
        else:
            st.info("ライフゴールを設定してください")
            if st.button("➕ Add Goal"):
                st.session_state.current_page = "Goals"
                st.rerun()
    except Exception as e:
        st.info("Set up goals to see progress tracking")
    
    st.markdown("---")
    
    # Expense Breakdown
    st.subheader("💸 Expense Breakdown (6 months)")
    
    if cash_flow.expense_by_category:
        categories = list(cash_flow.expense_by_category.keys())
        amounts = [float(v) for v in cash_flow.expense_by_category.values()]
        
        fig = px.bar(
            x=amounts,
            y=categories,
            orientation='h',
            title="Expenses by Category",
            labels={'x': 'Amount (¥)', 'y': 'Category'},
        )
        fig.update_traces(marker_color='#6366f1')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No expense data available")
    
    # Replacement Alerts
    if dep_summary.assets_requiring_replacement:
        st.subheader("⚠️ Replacement Alerts")
        for asset in dep_summary.assets_requiring_replacement[:5]:
            days_text = "過期" if asset.remaining_days <= 0 else f"{asset.remaining_days}日後"
            st.warning(f"🔧 **{asset.asset_name}** - 買い替え: {days_text} (取得価額: ¥{asset.acquisition_price:,.0f})")


def _render_empty_dashboard():
    """Render empty state dashboard"""
    st.info("""
    ### 🚀 Getting Started
    
    1. **Initialize Database**: Run `python scripts/db_init.py`
    2. **Import Data**: Go to Import page to upload CSVs
    3. **Set Goals**: Configure your financial goals
    4. **Track Progress**: View your dashboard
    """)
    
    # Sample data visualization
    st.subheader("📊 Sample Dashboard Preview")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Net Worth", "¥5,000,000", "+12%")
    with col2:
        st.metric("Savings Rate", "25%", "+5%")
    with col3:
        st.metric("Runway", "18 months", "Healthy")
    with col4:
        st.metric("Goal Progress", "65%", "+3%")
