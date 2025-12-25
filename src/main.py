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

# Modern CSS - Clean button-style navigation like LBS Control
st.markdown("""
<style>
    /* Import modern font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* Global styles */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Dark sidebar */
    [data-testid="stSidebar"] {
        background-color: #0f172a;
    }
    
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #e2e8f0;
    }
    
    /* Hide default radio button styling */
    [data-testid="stSidebar"] .stRadio {
        display: none;
    }
    
    /* App branding header */
    .sidebar-header {
        display: flex;
        align-items: center;
        padding: 1.25rem 1rem;
        gap: 0.75rem;
        border-bottom: 1px solid #1e293b;
        margin-bottom: 1.5rem;
    }
    
    .sidebar-header .logo {
        width: 36px;
        height: 36px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        border-radius: 0.5rem;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.25rem;
    }
    
    .sidebar-header .title {
        font-size: 1.125rem;
        font-weight: 600;
        color: #f1f5f9;
    }
    
    /* Navigation items */
    .nav-item {
        display: flex;
        align-items: center;
        padding: 0.75rem 1rem;
        margin: 0.125rem 0.5rem;
        border-radius: 0.5rem;
        color: #94a3b8;
        cursor: pointer;
        transition: all 0.15s ease;
        font-size: 0.9rem;
        font-weight: 500;
        text-decoration: none;
    }
    
    .nav-item:hover {
        background-color: #1e293b;
        color: #f1f5f9;
    }
    
    .nav-item.active {
        background-color: #1e293b;
        color: #ffffff;
    }
    
    .nav-item .icon {
        width: 20px;
        margin-right: 0.75rem;
        font-size: 1rem;
        opacity: 0.8;
    }
    
    /* Main header styles */
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.25rem;
    }
    
    .sub-header {
        color: #64748b;
        font-size: 1rem;
        margin-bottom: 1.5rem;
    }
    
    /* Metric cards with subtle styling */
    .stMetric {
        background: #ffffff;
        padding: 1rem;
        border-radius: 0.75rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border: 1px solid #e2e8f0;
    }
    
    /* Button styling */
    .stButton > button {
        border-radius: 0.5rem;
        font-weight: 500;
        transition: all 0.15s ease;
    }
    
    /* Footer */
    .sidebar-footer {
        position: fixed;
        bottom: 0;
        width: inherit;
        padding: 1rem;
        border-top: 1px solid #1e293b;
        background: #0f172a;
    }
    
    .sidebar-footer p {
        color: #475569;
        font-size: 0.7rem;
        text-align: center;
        margin: 0;
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
    
    # Navigation configuration
    nav_items = [
        ("grid", "Dashboard", "Dashboard"),
        ("briefcase", "Assets", "Assets"),
        ("target", "Goals", "Goals"),
        ("download", "Import", "Import"),
        ("search", "Purchase Audit", "Audit"),
        ("settings", "Settings", "Settings"),
    ]
    
    # Sidebar
    with st.sidebar:
        # Header with logo
        st.markdown("""
        <div class="sidebar-header">
            <div class="logo">💰</div>
            <span class="title">Asset Mgmt</span>
        </div>
        """, unsafe_allow_html=True)
        
        # Navigation buttons
        for icon, label, page_key in nav_items:
            is_active = st.session_state.current_page == page_key
            
            if st.button(
                f"{'📊' if icon == 'grid' else '💼' if icon == 'briefcase' else '🎯' if icon == 'target' else '📥' if icon == 'download' else '🔍' if icon == 'search' else '⚙️'}  {label}",
                key=f"nav_{page_key}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state.current_page = page_key
                st.rerun()
        
        # Spacer and footer
        st.markdown("<br>" * 10, unsafe_allow_html=True)
        st.caption("Asset Management v2.0")
    
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
