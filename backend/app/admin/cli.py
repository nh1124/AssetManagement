"""Audited administrator CLI: python -m app.admin.cli."""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from sqlalchemy.exc import IntegrityError

from ..domain.admin_permissions import PRESETS, validate_permissions
from ..domain.errors import DomainError, Invalid, NotFound, Refused
from ..domain.messages import message_of
from ..services import admin_audit_service as audit, admin_auth_service as admins
from ..services import client_service as clients, system_settings_service as settings
from ..workflows import admin_account_workflow as workflow


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--yes", action="store_true")
    groups = parser.add_subparsers(dest="group", required=True)

    def group(name):
        p = groups.add_parser(name)
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--yes", action="store_true", default=argparse.SUPPRESS)
        return p.add_subparsers(dest="command", required=True)

    def command(sub, name):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--yes", action="store_true", default=argparse.SUPPRESS)
        return p

    sub = group("admin")
    p = command(sub, "create")
    p.add_argument("username")
    p.add_argument("--preset", choices=sorted(PRESETS))
    p.add_argument("--permission", nargs="+", action="extend", default=[])
    command(sub, "list")
    for name in ("disable", "enable", "reset-mfa", "grant", "revoke"):
        p = command(sub, name)
        p.add_argument("username")
        if name in {"grant", "revoke"}:
            p.add_argument("permissions", nargs="+")

    sub = group("client")
    p = command(sub, "list")
    p.add_argument("--status", choices=("active", "suspended", "pending", "locked"))
    p.add_argument("--query")
    p = command(sub, "create")
    p.add_argument("username")
    p.add_argument("--name", required=True)
    p.add_argument("--email")
    for name in ("show", "suspend", "reactivate", "approve", "unlock", "sign-out", "reset-password", "reset-mfa"):
        p = command(sub, name)
        p.add_argument("id", type=int)
        if name == "suspend":
            p.add_argument("--reason", required=True)

    sub = group("health")
    p = command(sub, "check")
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--client", type=int)
    scope.add_argument("--all-clients", action="store_true")
    p = command(sub, "repair")
    p.add_argument("--client", required=True, type=int)

    sub = group("settings")
    p = command(sub, "get")
    p.add_argument("key", nargs="?")
    p = command(sub, "set")
    p.add_argument("key")
    p.add_argument("value")
    sub = group("audit")
    p = command(sub, "tail")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--action")
    return parser


def _output(value, *, as_json, out):
    if as_json:
        print(json.dumps(value, ensure_ascii=False, default=str), file=out)
        return
    rows = value if isinstance(value, list) else [value]
    if not rows:
        print("(empty)", file=out)
        return
    if not all(isinstance(row, dict) for row in rows):
        print(str(value), file=out)
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    cells = [[json.dumps(row.get(key), ensure_ascii=False, default=str) if isinstance(row.get(key), (list, dict))
              else str(row.get(key, "")) for key in keys] for row in rows]
    widths = [max(len(key), *(len(row[i]) for row in cells)) for i, key in enumerate(keys)]
    print(" | ".join(key.ljust(width) for key, width in zip(keys, widths)), file=out)
    print("-+-".join("-" * width for width in widths), file=out)
    for row in cells:
        print(" | ".join(cell.ljust(width) for cell, width in zip(row, widths)), file=out)


def _health_result(client_id, result, *, summary=False):
    health = result.get("health", result)
    row = {"client_id": client_id, **{key: health[key] for key in ("status", "total_issues", "repairable_groups")}}
    if "actions" in result:
        row["actions"] = result["actions"]
    if not summary:
        row["issues"] = [{**issue, "items": issue["items"][:20]} for issue in health["issues"] if issue["count"]]
    return row


def _dispatch(args, db, actor, input_fn, getpass_fn, emit):
    if args.group == "admin":
        if args.command == "list":
            return admins.list_admins(db)
        if args.command == "create":
            preset = args.preset or ("owner" if not admins.list_admins(db) else None)
            permissions = validate_permissions((PRESETS[preset] if preset else frozenset()) | frozenset(args.permission))
            password = getpass_fn("Password: ")
            if password != getpass_fn("Password (again): "):
                raise Invalid("Passwords do not match.", ja="パスワードが一致しません。")
            admin, provisioning = workflow.admin_create(db, args.username, password, permissions=permissions, actor=actor)
            emit({"id": admin.id, **provisioning})
            workflow.admin_confirm_totp(db, admin.id, input_fn("6-digit code: "), actor=actor)
            return {"id": admin.id, "username": admin.username, "mfa_enabled": admin.mfa_enabled}
        admin = admins.get_by_username(db, args.username)
        if admin is None:
            raise NotFound("Administrator not found.", ja="管理者が見つかりません。")
        operation = getattr(workflow, "admin_" + args.command.replace("-", "_"))
        if args.command in {"grant", "revoke"}:
            operation(db, admin.id, args.permissions, actor=actor)
        else:
            result = operation(db, admin.id, actor=actor)
            if args.command == "reset-mfa":
                return {"id": admin.id, "temporary_password": result}
        return {"id": admin.id, "username": admin.username, "is_active": admin.is_active,
                "permissions": sorted(admins.permissions_for(db, admin))}

    if args.group == "client":
        if args.command == "list":
            return clients.admin_list(db, status=args.status, query=args.query, limit=1000, offset=0)
        if args.command == "show":
            return clients.admin_summary(db, clients.get_by_id(db, args.id))
        if args.command == "create":
            client, password = workflow.client_create(db, args.username, args.name, args.email, actor=actor)
            return {"id": client.id, "username": client.username, "temporary_password": password}
        operation = getattr(workflow, "client_" + args.command.replace("-", "_"))
        if args.command == "suspend":
            operation(db, args.id, args.reason, actor=actor)
        else:
            result = operation(db, args.id, actor=actor)
            if args.command in {"reset-password", "reset-mfa"}:
                return {"id": args.id, "temporary_password": result}
        return clients.admin_summary(db, clients.get_by_id(db, args.id))

    if args.group == "health":
        if args.command == "repair":
            return _health_result(args.client, workflow.health_repair(db, args.client, actor=actor))
        ids = clients.admin_client_ids(db) if args.all_clients else [args.client]
        results = [_health_result(client_id, workflow.health_check(db, client_id, actor=actor), summary=args.all_clients)
                   for client_id in ids]
        return results if args.all_clients else results[0]

    if args.group == "settings":
        if args.command == "get":
            if args.key:
                settings.get(db, args.key)  # Validate unknown keys.
                return {args.key: settings.all(db)[args.key]}
            return settings.all(db)
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        workflow.settings_set(db, args.key, value, actor=actor)
        return {args.key: settings.all(db)[args.key]}

    return [{key: getattr(row, key) for key in ("id", "at", "actor", "action", "admin_user_id", "target_client_id",
                                               "target_admin_id", "detail", "result", "ip", "correlation_id")}
            for row in audit.list_logs(db, limit=args.limit, action_prefix=args.action)]


def main(argv=None, *, db=None, input_fn=input, getpass_fn=getpass.getpass, out=sys.stdout):
    args = _parser().parse_args(argv)
    mutating = ((args.group == "admin" and args.command != "list")
                or (args.group == "client" and args.command not in {"list", "show"})
                or (args.group == "health" and args.command == "repair")
                or (args.group == "settings" and args.command == "set"))
    emit = lambda value: _output(value, as_json=args.json, out=out)
    if mutating and not args.yes and input_fn("続行しますか？ [y/N]").strip().lower() != "y":
        emit({"result": "cancelled"})
        return 1
    owned = db is None
    if owned:
        from ..database import SessionLocal
        db = SessionLocal()
    try:
        result = _dispatch(args, db, "cli:" + getpass.getuser(), input_fn, getpass_fn, emit)
        emit(result)
        return 0
    except DomainError as exc:
        emit({"result": "refused" if isinstance(exc, Refused) else "failed",
              "message": message_of(exc)})
        return 1
    except IntegrityError:
        emit({"result": "failed", "message": "Username or email already exists."})
        return 1
    except (EOFError, KeyboardInterrupt):
        emit({"result": "cancelled"})
        return 1
    finally:
        if owned:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
