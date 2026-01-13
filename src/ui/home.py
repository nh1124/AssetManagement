import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from services.logic import FinanceService

def render_home():
    service = FinanceService()
    
    st.markdown('<h2 class="main-header">Cockpit Dashboard</h2>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Macro View: Long-term trends & Goal achievement</p>', unsafe_allow_html=True)

    # Top Row: KPI Metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Gauge Chart for Goal Probability
        prob = service.get_goal_probability()
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = prob,
            title = {'text': "Goal Probability"},
            domain = {'x': [0, 1], 'y': [0, 1]},
            gauge = {
                'axis': {'range': [None, 100]},
                'bar': {'color': "#6366f1"},
                'steps': [
                    {'range': [0, 50], 'color': "#fee2e2"},
                    {'range': [50, 80], 'color': "#fef3c7"},
                    {'range': [80, 100], 'color': "#dcfce7"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 90
                }
            }
        ))
        fig_gauge.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col2:
        runway = service.get_runway_months()
        st.metric(label="Runway", value=f"{runway} Months", delta="Healthy", delta_color="normal")
        st.info("Estimated months of survival based on current burn rate.")
        
    with col3:
        budget = service.get_budget_status()
        st.write("**This Month's Budget**")
        progress = budget["used"] / budget["limit"]
        st.progress(progress, text=f"Used ¥{budget['used']:,} / Limit ¥{budget['limit']:,}")
        if progress > 0.8:
            st.warning("Approaching budget limit!")

    st.markdown("---")

    # Main Row: Asset Trend
    st.subheader("Asset Value vs. Ideal Trajectory")
    history_df = service.get_history()
    ideal_df = service.get_ideal_trajectory()
    
    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(x=history_df["date"], y=history_df["value"], mode='lines', name='Actual Value', line=dict(color='#6366f1', width=3)))
    fig_trend.add_trace(go.Scatter(x=ideal_df["date"], y=ideal_df["ideal_value"], mode='lines', name='Ideal Trajectory', line=dict(color='#94a3b8', dash='dash')))
    
    fig_trend.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis_title="Date",
        yaxis_title="JPY",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=0, r=0, t=30, b=0)
    )
    st.plotly_chart(fig_trend, use_container_width=True)
