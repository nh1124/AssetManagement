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
    page_title="Asset Management",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# LBS Control Style CSS
st.markdown("""
<style>
    /* Import font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    
    * {
        font-family: 'Inter', sans-serif;
    }
    
    /* Sidebar - Dark theme matching LBS */
    section[data-testid="stSidebar"] {
        background-color: #0a0a0f;
        border-right: 1px solid #1a1a2e;
    }
    
    section[data-testid="stSidebar"] > div {
        padding-top: 0;
    }
    
    /* Hide streamlit branding */
    #MainMenu, footer, header {
        visibility: hidden;
    }
    
    /* Custom navigation container */
    .nav-container {
        padding: 0.5rem;
    }
    
    /* Sidebar header - Logo + Title */
    .sidebar-brand {
        display: flex;
        align-items: center;
        padding: 1rem 0.75rem;
        gap: 0.625rem;
        margin-bottom: 1.5rem;
    }
    
    .sidebar-brand .logo-box {
        width: 32px;
        height: 32px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1rem;
    }
    
    .sidebar-brand .brand-text {
        font-size: 1rem;
        font-weight: 600;
        color: #a78bfa;
    }
    
    /* Navigation items - LBS style */
    .nav-item {
        display: flex;
        align-items: center;
        padding: 0.625rem 0.75rem;
        margin: 2px 0;
        border-radius: 6px;
        color: #9ca3af;
        cursor: pointer;
        transition: all 0.15s ease;
        font-size: 0.875rem;
        font-weight: 500;
        text-decoration: none !important;
    }
    
    .nav-item:hover {
        background-color: rgba(99, 102, 241, 0.1);
        color: #e5e7eb;
    }
    
    .nav-item.active {
        background-color: rgba(99, 102, 241, 0.15);
        color: #ffffff;
    }
    
    .nav-item .nav-icon {
        width: 18px;
        height: 18px;
        margin-right: 0.75rem;
        opacity: 0.7;
    }
    
    /* Footer section */
    .sidebar-footer {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 260px;
        padding: 0.75rem;
        background: #0a0a0f;
        border-top: 1px solid #1a1a2e;
    }
    
    .footer-box {
        background: #111118;
        border-radius: 8px;
        padding: 0.75rem;
    }
    
    .footer-label {
        font-size: 0.65rem;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.25rem;
    }
    
    .footer-status {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.8rem;
        color: #d1d5db;
    }
    
    .status-dot {
        width: 8px;
        height: 8px;
        background: #10b981;
        border-radius: 50%;
    }
    
    /* Hide default streamlit elements in sidebar */
    section[data-testid="stSidebar"] .stButton button {
        background: transparent;
        border: none;
        color: #9ca3af;
        text-align: left;
        padding: 0.625rem 0.75rem;
        font-size: 0.875rem;
        font-weight: 500;
        width: 100%;
        border-radius: 6px;
        transition: all 0.15s ease;
    }
    
    section[data-testid="stSidebar"] .stButton button:hover {
        background-color: rgba(99, 102, 241, 0.1);
        color: #e5e7eb;
        border: none;
    }
    
    section[data-testid="stSidebar"] .stButton button:focus {
        box-shadow: none;
        border: none;
    }
    
    section[data-testid="stSidebar"] .stButton button[kind="primary"] {
        background-color: rgba(99, 102, 241, 0.15);
        color: #ffffff;
    }
    
    /* Main content styling */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }
    
    .page-header {
        margin-bottom: 0.5rem;
    }
    
    .page-header h1 {
        font-size: 1.75rem;
        font-weight: 600;
        color: #f9fafb;
        margin: 0;
    }
    
    .page-header p {
        color: #6b7280;
        font-size: 0.9rem;
        margin: 0.25rem 0 0 0;
    }
    
    /* Metric cards */
    div[data-testid="stMetric"] {
        background: #111118;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #1f1f2e;
    }
    
    div[data-testid="stMetric"] label {
        color: #9ca3af;
    }
    
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #f9fafb;
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
    
    # Navigation items
    nav_items = [
        ("📊", "Dashboard", "Dashboard"),
        ("💼", "Assets", "Assets"),
        ("🎯", "Goals", "Goals"),
        ("📥", "Import", "Import"),
        ("🔍", "Purchase Audit", "Audit"),
        ("⚙️", "Settings", "Settings"),
    ]
    
    # Sidebar
    with st.sidebar:
        # Brand header
        st.markdown("""
        <div class="sidebar-brand">
            <div class="logo-box">💰</div>
            <span class="brand-text">Asset Mgmt</span>
        </div>
        """, unsafe_allow_html=True)
        
        # Navigation
        for icon, label, page_key in nav_items:
            is_active = st.session_state.current_page == page_key
            
            if st.button(
                f"{icon}  {label}",
                key=f"nav_{page_key}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state.current_page = page_key
                st.rerun()
        
        # Footer
        st.markdown("<br>" * 8, unsafe_allow_html=True)
        st.markdown("""
        <div class="footer-box">
            <div class="footer-label">System Status</div>
            <div class="footer-status">
                <span class="status-dot"></span>
                <span>Database Connected</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Main content
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
