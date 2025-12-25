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

# Modern CSS with glassmorphism and gradients
st.markdown("""
<style>
    /* Import modern font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* Global styles */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Main header styles */
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
    }
    
    .sub-header {
        color: #64748b;
        font-size: 1.1rem;
        margin-bottom: 2rem;
        font-weight: 400;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e1b4b 0%, #312e81 50%, #4338ca 100%);
    }
    
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #e0e7ff;
    }
    
    [data-testid="stSidebar"] .stRadio > label {
        color: #c7d2fe !important;
    }
    
    [data-testid="stSidebar"] hr {
        border-color: rgba(255,255,255,0.1);
    }
    
    /* Sidebar navigation buttons */
    .nav-link {
        display: flex;
        align-items: center;
        padding: 0.875rem 1rem;
        margin: 0.25rem 0;
        border-radius: 0.75rem;
        color: #c7d2fe;
        text-decoration: none;
        transition: all 0.2s ease;
        font-weight: 500;
        cursor: pointer;
    }
    
    .nav-link:hover {
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }
    
    .nav-link.active {
        background: rgba(255,255,255,0.15);
        color: #ffffff;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .nav-icon {
        font-size: 1.25rem;
        margin-right: 0.75rem;
    }
    
    /* App branding */
    .app-brand {
        padding: 1.5rem 1rem;
        text-align: center;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        margin-bottom: 1rem;
    }
    
    .app-brand h1 {
        font-size: 1.5rem;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .app-brand p {
        font-size: 0.75rem;
        color: #a5b4fc;
        margin: 0.25rem 0 0 0;
        text-transform: uppercase;
        letter-spacing: 0.1em;
    }
    
    /* Metric cards */
    .stMetric {
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        padding: 1.25rem;
        border-radius: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
        border: 1px solid #e2e8f0;
    }
    
    .stMetric:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05);
        transition: all 0.2s ease;
    }
    
    /* Status colors */
    .positive {
        color: #10b981;
    }
    
    .negative {
        color: #ef4444;
    }
    
    /* Progress bars */
    .stProgress > div > div {
        background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
        border-radius: 9999px;
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        background: #f8fafc;
        border-radius: 0.5rem;
    }
    
    /* Form styling */
    .stForm {
        background: #ffffff;
        padding: 1.5rem;
        border-radius: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        border: 1px solid #e2e8f0;
    }
    
    /* Button styling */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
        border: none;
        border-radius: 0.5rem;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
    }
    
    /* Footer */
    .sidebar-footer {
        position: absolute;
        bottom: 1rem;
        left: 0;
        right: 0;
        text-align: center;
        padding: 1rem;
        border-top: 1px solid rgba(255,255,255,0.1);
    }
    
    .sidebar-footer p {
        color: #818cf8;
        font-size: 0.75rem;
        margin: 0.25rem 0;
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
        # App branding
        st.markdown("""
        <div class="app-brand">
            <h1>💰 Asset Mgmt</h1>
            <p>Personal Finance System</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Navigation menu
        pages = {
            "📊 Dashboard": "Dashboard",
            "💼 Assets": "Assets", 
            "🎯 Goals": "Goals",
            "📥 Import": "Import",
            "🔍 Purchase Audit": "Audit",
            "⚙️ Settings": "Settings",
        }
        
        # Use selectbox for cleaner look
        st.markdown("##### Navigation")
        selected = st.radio(
            "Navigation",
            options=list(pages.keys()),
            label_visibility="collapsed",
            key="main_nav"
        )
        st.session_state.current_page = pages[selected]
        
        # Spacer
        st.markdown("<br>" * 5, unsafe_allow_html=True)
        
        # Footer info
        st.markdown("---")
        st.markdown("""
        <div style="text-align: center; padding: 0.5rem;">
            <p style="color: #a5b4fc; font-size: 0.75rem; margin: 0;">
                Asset Management v2.0
            </p>
            <p style="color: #6366f1; font-size: 0.65rem; margin: 0.25rem 0 0 0;">
                Python-Native • Local-First
            </p>
        </div>
        """, unsafe_allow_html=True)
    
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
