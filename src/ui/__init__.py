"""
Asset Management System - UI Module
Streamlit components and pages.
"""

from .dashboard import render_dashboard
from .components import (
    render_sidebar,
    render_assets_page,
    render_goals_page,
    render_import_page,
    render_audit_page,
    render_settings_page,
)

__all__ = [
    "render_dashboard",
    "render_sidebar",
    "render_assets_page",
    "render_goals_page",
    "render_import_page",
    "render_audit_page",
    "render_settings_page",
]
