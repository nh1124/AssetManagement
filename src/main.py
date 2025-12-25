"""
Asset Management System - Streamlit Main Entry Point
次世代金融資産管理システム
"""

import streamlit as st
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from ui.dashboard import render_dashboard
from ui.components import (
    render_sidebar,
    render_assets_page,
    render_goals_page,
    render_import_page,
    render_audit_page,
    render_settings_page,
)

# Page configuration
st.set_page_config(
    page_title="Asset Management System",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 1rem;
    }
    .sub-header {
        color: #6b7280;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        color: white;
    }
    .positive {
        color: #10b981;
    }
    .negative {
        color: #ef4444;
    }
    .stMetric {
        background-color: #f8fafc;
        padding: 1rem;
        border-radius: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main application entry point"""
    
    # Initialize session state
    if 'db_url' not in st.session_state:
        st.session_state.db_url = "sqlite:///data/assets.db"
    
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Dashboard"
    
    # Sidebar navigation
    with st.sidebar:
        st.image("https://via.placeholder.com/150x50?text=Asset+Mgmt", width=150)
        st.markdown("---")
        
        # Navigation
        pages = {
            "📊 Dashboard": "Dashboard",
            "💼 Assets": "Assets",
            "🎯 Goals": "Goals",
            "📥 Import": "Import",
            "🔍 Purchase Audit": "Audit",
            "⚙️ Settings": "Settings",
        }
        
        selected = st.radio(
            "Navigation",
            options=list(pages.keys()),
            label_visibility="collapsed",
        )
        st.session_state.current_page = pages[selected]
        
        st.markdown("---")
        st.caption("Asset Management System v2.0")
        st.caption("Python-Native & Local-First")
    
    # Main content area
    page = st.session_state.current_page
    
    if page == "Dashboard":
        render_dashboard(st.session_state.db_url)
    elif page == "Assets":
        render_assets_page(st.session_state.db_url)
    elif page == "Goals":
        render_goals_page(st.session_state.db_url)
    elif page == "Import":
        render_import_page(st.session_state.db_url)
    elif page == "Audit":
        render_audit_page(st.session_state.db_url)
    elif page == "Settings":
        render_settings_page(st.session_state.db_url)


if __name__ == "__main__":
    main()
