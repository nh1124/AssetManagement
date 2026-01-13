import streamlit as st
import plotly.graph_objects as go
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def render_strategy():
    st.markdown('<h2 class="main-header">The Boardroom: Strategy</h2>', unsafe_allow_html=True)
    
    st.subheader("Life Event Timeline")
    events = [
        {"Event": "Wedding", "Date": "2024-06", "Cost": "3.0M"},
        {"Event": "New Car", "Date": "2025-10", "Cost": "4.5M"},
        {"Event": "House Downpayment", "Date": "2028-01", "Cost": "5.0M"}
    ]
    st.table(events)

    st.markdown("---")
    st.subheader("Asset Growth Simulator")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.write("**Parameters**")
        initial_investment = st.slider("Initial Investment (M JPY)", 0, 20, 5)
        monthly_investment = st.slider("Monthly Contribution (k JPY)", 0, 500, 50)
        expected_return = st.slider("Expected Return (%)", 0.0, 15.0, 5.0)
        years = st.slider("Time Horizon (Years)", 1, 40, 30)
        target_amount = st.number_input("Target Amount (M JPY)", value=50)

    with col2:
        # Simulation Logic
        months = years * 12
        monthly_rate = expected_return / 100 / 12
        
        # FV Calculation monthly
        balances = []
        current_balance = initial_investment * 1000000
        for i in range(months + 1):
            balances.append(current_balance)
            current_balance = (current_balance + (monthly_investment * 1000)) * (1 + monthly_rate)
            
        dates = [datetime.now() + timedelta(days=30*i) for i in range(months + 1)]
        df_sim = pd.DataFrame({"Date": dates, "Projected": balances})
        df_sim["Target"] = target_amount * 1000000
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_sim["Date"], y=df_sim["Projected"], mode='lines', name='Projected Growth', fill='tozeroy'))
        fig.add_trace(go.Scatter(x=df_sim["Date"], y=df_sim["Target"], mode='lines', name='Target', line=dict(dash='dash', color='red')))
        
        fig.update_layout(title="Wealth Projection", yaxis_title="JPY")
        st.plotly_chart(fig, use_container_width=True)
        
        if balances[-1] >= target_amount * 1000000:
            st.success(f"🎉 Goal Achievable! Projected Final: ¥{balances[-1]:,.0f}")
        else:
            diff = (target_amount * 1000000) - balances[-1]
            st.error(f"⚠️ Shortfall: ¥{diff:,.0f}. Increase contribution or horizon.")
