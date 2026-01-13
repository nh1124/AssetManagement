import streamlit as st
from services.logic import FinanceService

def render_analytics():
    service = FinanceService()
    
    st.markdown('<h2 class="main-header">The Lab: Micro Analytics</h2>', unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["💎 Asset Inventory", "📊 P/L Summary"])
    
    with tab1:
        st.subheader("Raw Asset List")
        assets_df = service.get_assets_df()
        
        # Filtering
        categories = assets_df["category"].unique().tolist()
        selected_cat = st.multiselect("Filter by Category", categories, default=categories)
        
        filtered_df = assets_df[assets_df["category"].isin(selected_cat)]
        
        st.data_editor(
            filtered_df,
            column_config={
                "value_jpy": st.column_config.NumberColumn("Value (JPY)", format="¥%d"),
                "acquisition_date": st.column_config.DateColumn("Acquired"),
            },
            hide_index=True,
            use_container_width=True
        )

    with tab2:
        st.subheader("Monthly Profit & Loss")
        pl_df = service.get_transactions_summary()
        
        st.table(pl_df.style.format({"Income": "¥{:,}", "Expenses": "¥{:,}", "Net P/L": "¥{:,}"}))
        
        # Simple bar chart for P/L
        st.bar_chart(pl_df.set_index("Month")[["Income", "Expenses"]])
