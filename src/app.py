import streamlit as st
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from ui.home import render_home
from ui.analytics import render_analytics
from ui.journal import render_journal
from ui.strategy import render_strategy

# Page configuration
st.set_page_config(
    page_title="Cockpit",
    page_icon="🛳️",
    layout="wide",
)

# Custom Styling (LBS Control Vibe)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    [data-testid="stSidebar"] {
        background-color: #0f172a;
        color: #f8fafc;
    }
    
    .main-header {
        font-size: 2.25rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0px;
    }
    
    .sub-header {
        color: #64748b;
        font-size: 1rem;
        margin-bottom: 24px;
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #94a3b8;
    }
</style>
""", unsafe_allow_html=True)

def main():
    # Sidebar Branding
    st.sidebar.markdown("""
    <div style="padding: 1rem 0; text-align: center;">
        <h2 style="color: #ffffff; margin:0;">COCKPIT</h2>
        <p style="color: #6366f1; font-size: 0.75rem; font-weight: 600;">Personal Asset Management</p>
    </div>
    """, unsafe_allow_html=True)

    # Navigation
    menu = {
        "🏠 Home": "Home",
        "🧪 Analytics": "Analytics",
        "📒 Journal": "Journal",
        "♟️ Strategy": "Strategy"
    }
    
    choice = st.sidebar.radio("Navigation", list(menu.keys()), label_visibility="collapsed")
    page = menu[choice]

    st.sidebar.markdown("---")
    st.sidebar.caption("v2.0 Mockup • AGENTIC_BUILD")

    if page == "Home":
        render_home()
    elif page == "Analytics":
        render_analytics()
    elif page == "Journal":
        render_journal()
    elif page == "Strategy":
        render_strategy()

if __name__ == "__main__":
    main()
