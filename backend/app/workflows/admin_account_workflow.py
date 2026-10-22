"""Administrative operations: the state change and its audit share one commit.

The CLI is an OS-authorized entrypoint. Wave 2 must check capabilities and step-up
before invoking these operations; actor strings are attribution, not credentials.
"""
from sqlalchemy.exc import IntegrityError

from ..domain.errors import Conflict, DomainError, Refused
from ..services import admin_audit_service as audit, admin_auth_service as admins
from ..services import client_service as clients, data_health_service as health, mfa_service, system_settings_service as settings


def _run(db, actor, action, operation, *, admin_user_id=None, target_client_id=None,
         target_admin_id=None, detail=None, created_target=None):
    try:
        result = operation()
        if created_target:
            target = result[0] if isinstance(result, tuple) else result
            if created_target == "client":
                target_client_id = target.id
            else:
                target_admin_id = target.id
        audit.record(db, actor, action, admin_user_id=admin_user_id, target_client_id=target_client_id,
                     target_admin_id=target_admin_id, detail=detail)
        db.commit()
        return result
    except DomainError as exc:
        db.rollback()
        audit.record(db, actor, action, admin_user_id=admin_user_id, target_client_id=target_client_id,
                     target_admin_id=target_admin_id, detail=detail,
                     result="refused" if isinstance(exc, Refused) else "failed")
        db.commit()
        raise
    except IntegrityError as exc:
        db.rollback()
        audit.record(db, actor, action, admin_user_id=admin_user_id, target_client_id=target_client_id,
                     target_admin_id=target_admin_id, detail=detail, result="failed")
        db.commit()
        raise Conflict("The operation conflicts with an existing record.", ja="既存の記録と競合するため操作できません。") from exc
    except Exception:
        db.rollback()
        raise


def client_create(db, username, name, email=None, *, actor, admin_user_id=None):
    return _run(db, actor, "client.create", lambda: clients.create_by_admin(db, username, name, email, commit=False),
                admin_user_id=admin_user_id, created_target="client")


def _client_operation(db, client_id, operation, action, actor, admin_user_id, **kwargs):
    return _run(db, actor, action,
                lambda: operation(db, clients.get_by_id(db, client_id), commit=False, **kwargs),
                admin_user_id=admin_user_id, target_client_id=client_id)


def client_suspend(db, client_id, reason, *, actor, admin_user_id=None):
    return _client_operation(db, client_id, clients.suspend, "client.suspend", actor, admin_user_id, reason=reason)


def client_reactivate(db, client_id, *, actor, admin_user_id=None):
    return _client_operation(db, client_id, clients.reactivate, "client.reactivate", actor, admin_user_id)


def client_approve(db, client_id, *, actor, admin_user_id=None):
    return _client_operation(db, client_id, clients.approve, "client.approve", actor, admin_user_id)


def client_unlock(db, client_id, *, actor, admin_user_id=None):
    return _client_operation(db, client_id, clients.unlock, "client.unlock", actor, admin_user_id)


def client_sign_out(db, client_id, *, actor, admin_user_id=None):
    return _client_operation(db, client_id, clients.sign_out, "client.sign_out", actor, admin_user_id)


def client_reset_password(db, client_id, *, actor, admin_user_id=None):
    return _client_operation(db, client_id, clients.reset_password, "client.reset_password", actor, admin_user_id)


def client_reset_mfa(db, client_id, *, actor, admin_user_id=None):
    def operation():
        client = clients.get_by_id(db, client_id)
        mfa_service.remove_factor(db, client, commit=False)
        return clients.reset_password(db, client, commit=False)
    return _run(db, actor, "client.reset_mfa", operation, admin_user_id=admin_user_id, target_client_id=client_id)


def health_check(db, client_id, *, actor, admin_user_id=None):
    def operation():
        clients.get_by_id(db, client_id)
        return health.check_data_health(db, client_id)  # All audiences.
    return _run(db, actor, "health.check", operation, admin_user_id=admin_user_id, target_client_id=client_id)


def health_repair(db, client_id, *, actor, admin_user_id=None):
    def operation():
        clients.get_by_id(db, client_id)
        return health.repair_data_health(db, client_id, commit=False)
    return _run(db, actor, "health.repair", operation, admin_user_id=admin_user_id, target_client_id=client_id)


def settings_set(db, key, value, *, actor, admin_user_id=None):
    return _run(db, actor, "settings.set", lambda: settings.set(db, key, value, actor, commit=False),
                admin_user_id=admin_user_id, detail={"key": key})


def admin_create(db, username, password, *, permissions=(), actor, admin_user_id=None):
    return _run(db, actor, "admin.create", lambda: admins.create(db, username, password, actor, permissions=permissions, commit=False),
                admin_user_id=admin_user_id, created_target="admin")


def _admin_operation(db, admin_id, operation, action, audit_actor, admin_user_id, **kwargs):
    return _run(db, audit_actor, action, lambda: operation(db, admins.get_by_id(db, admin_id), commit=False, **kwargs),
                admin_user_id=admin_user_id, target_admin_id=admin_id)


def admin_disable(db, admin_id, *, actor, admin_user_id=None):
    return _admin_operation(db, admin_id, admins.disable, "admin.disable", actor, admin_user_id)


def admin_enable(db, admin_id, *, actor, admin_user_id=None):
    return _admin_operation(db, admin_id, admins.enable, "admin.enable", actor, admin_user_id)


def admin_reset_mfa(db, admin_id, *, actor, admin_user_id=None):
    return _admin_operation(db, admin_id, admins.reset_mfa, "admin.reset_mfa", actor, admin_user_id)


def admin_confirm_totp(db, admin_id, code, *, actor, admin_user_id=None):
    # Persist failures/lockout together with the refused audit, without rolling
    # back the failure counter as the ordinary refusal path would do.
    try:
        admin = admins.get_by_id(db, admin_id)
        valid = admins.confirm_totp(db, admin, code, commit=False)
        audit.record(db, actor, "admin.confirm_totp", admin_user_id=admin_user_id,
                     target_admin_id=admin_id, result="ok" if valid else "refused")
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not valid:
        raise Refused("Invalid MFA code or administrator is locked.", ja="認証コードが正しくないか、管理者がロックされています。")
    return admin


def admin_grant(db, admin_id, permissions, *, actor, admin_user_id=None):
    return _admin_operation(db, admin_id, admins.grant, "admin.grant", actor, admin_user_id, permissions=permissions, actor=actor)


def admin_revoke(db, admin_id, permissions, *, actor, admin_user_id=None):
    return _admin_operation(db, admin_id, admins.revoke, "admin.revoke", actor, admin_user_id, permissions=permissions, actor=actor)


def admin_set_permissions(db, admin_id, permissions, *, actor, admin_user_id=None):
    return _admin_operation(db, admin_id, admins.set_permissions, "admin.set_permissions", actor, admin_user_id, permissions=permissions, actor=actor)
