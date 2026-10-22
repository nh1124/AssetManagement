"""Owns the installation's administrator audit trail."""
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid

_SECRET_MARKERS = ("password", "secret", "recovery", "cookie", "token", "manual_entry", "otpauth")


def _validate_detail(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if any(marker in key.lower() for marker in _SECRET_MARKERS):
                raise Invalid("Credentials cannot be included in audit details.", ja="監査詳細に認証情報は記録できません。")
            _validate_detail(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_detail(item)


def record(db: Session, actor: str, action: str, *, admin_user_id=None, target_client_id=None,
           target_admin_id=None, detail=None, result="ok", ip=None, correlation_id=None, commit=False):
    if result not in {"ok", "refused", "failed"}:
        raise Invalid("Invalid audit result.", ja="監査結果が正しくありません。")
    _validate_detail(detail)
    row = models.AdminAuditLog(actor=actor, action=action, admin_user_id=admin_user_id,
                               target_client_id=target_client_id, target_admin_id=target_admin_id,
                               detail=detail if detail is not None else {}, result=result,
                               ip=ip, correlation_id=correlation_id)
    db.add(row)
    db.commit() if commit else db.flush()
    return row


def list_logs(db: Session, *, actor=None, action_prefix=None, target_client_id=None, target_admin_id=None,
              start_at=None, end_at=None, limit=100, offset=0):
    if not 1 <= limit <= 1000 or offset < 0:
        raise Invalid("Invalid pagination.", ja="ページの指定が正しくありません。")
    query = db.query(models.AdminAuditLog)
    for key, value in (("actor", actor), ("target_client_id", target_client_id), ("target_admin_id", target_admin_id)):
        if value is not None:
            query = query.filter(getattr(models.AdminAuditLog, key) == value)
    if action_prefix:
        query = query.filter(models.AdminAuditLog.action.startswith(action_prefix, autoescape=True))
    if start_at is not None:
        query = query.filter(models.AdminAuditLog.at >= start_at)
    if end_at is not None:
        query = query.filter(models.AdminAuditLog.at <= end_at)
    return query.order_by(models.AdminAuditLog.at.desc(), models.AdminAuditLog.id.desc()).limit(limit).offset(offset).all()
