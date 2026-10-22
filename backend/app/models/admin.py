"""Installation administration, deliberately separate from client data."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from ..database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (CheckConstraint("username = lower(username)", name="ck_admin_username_lower"),)

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    totp_secret_encrypted = Column(Text, nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    last_totp_step = Column(BigInteger, nullable=True)
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    tokens_valid_after = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(String, nullable=False)


class AdminUserPermission(Base):
    __tablename__ = "admin_user_permissions"
    __table_args__ = (UniqueConstraint("admin_user_id", "permission", name="uq_admin_permission"),)

    id = Column(Integer, primary_key=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False, index=True)
    permission = Column(String, nullable=False)
    granted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    granted_by = Column(String, nullable=False)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id = Column(String(64), primary_key=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    stage = Column(String, nullable=True)
    stepped_up_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (CheckConstraint("result IN ('ok', 'refused', 'failed')", name="ck_admin_audit_result"),)

    id = Column(Integer, primary_key=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False, index=True)
    target_client_id = Column(Integer, nullable=True)
    target_admin_id = Column(Integer, nullable=True)
    detail = Column(JSON, nullable=False, default=dict)
    result = Column(String, nullable=False)
    ip = Column(String, nullable=True)
    correlation_id = Column(String, nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_by = Column(String, nullable=False)
