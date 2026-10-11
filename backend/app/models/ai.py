from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base

class AiOperationPolicy(Base):
    __tablename__ = "ai_operation_policies"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "ai_client_id",
            "resource",
            "action",
            "risk",
            name="_client_ai_policy_uc",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    ai_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    resource = Column(String, nullable=False)
    action = Column(String, nullable=False)
    risk = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    threshold_amount = Column(Float, nullable=True)
    threshold_count = Column(Integer, nullable=True)
    require_mfa = Column(Boolean, default=False, server_default="false", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="ai_operation_policies", foreign_keys=[client_id])


class AiAuditLog(Base):
    __tablename__ = "ai_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    actor_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    ai_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    mcp_client_id = Column(String, nullable=True, index=True)
    source = Column(String, nullable=False)
    tool_name = Column(String, nullable=True)
    resource = Column(String, nullable=False)
    action = Column(String, nullable=False)
    risk = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    request_summary = Column(JSON, default=dict, nullable=False)
    diff_summary = Column(JSON, default=dict, nullable=False)
    result_summary = Column(JSON, default=dict, nullable=False)
    approval_request_id = Column(Integer, nullable=True)
    mfa_verified = Column(Boolean, default=False, server_default="false", nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="ai_audit_logs", foreign_keys=[client_id])


class AiChangeRequest(Base):
    __tablename__ = "ai_change_requests"
    __table_args__ = (
        UniqueConstraint("client_id", "idempotency_key", name="_client_ai_change_request_idempotency_uc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    created_by_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    ai_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    mcp_client_id = Column(String, nullable=True, index=True)
    source = Column(String, nullable=False)
    tool_name = Column(String, nullable=True)
    resource = Column(String, nullable=False)
    action = Column(String, nullable=False)
    risk = Column(String, nullable=False)
    status = Column(String, default="pending", server_default="pending", nullable=False, index=True)
    target_ref = Column(JSON, default=dict, nullable=False)
    input_payload = Column(JSON, default=dict, nullable=False)
    before_snapshot = Column(JSON, default=dict, nullable=False)
    after_snapshot = Column(JSON, default=dict, nullable=False)
    diff = Column(JSON, default=dict, nullable=False)
    validation = Column(JSON, default=dict, nullable=False)
    idempotency_key = Column(String, nullable=False)
    precondition_hash = Column(String, nullable=True)
    requires_mfa = Column(Boolean, default=False, server_default="false", nullable=False)
    approved_by_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    result = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="ai_change_requests", foreign_keys=[client_id])
