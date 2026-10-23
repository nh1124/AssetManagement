"""Injected CLI tests, including the useful retired WP30 maintenance cases."""
from datetime import date, datetime, timedelta
from io import StringIO
import json

import pyotp
import pytest
import sqlalchemy as sa

from app import models
from app.admin.cli import main
from app.domain.admin_permissions import ALL_PERMISSIONS, PRESETS
from app.services import admin_auth_service as admins, admin_audit_service as audit, system_settings_service as settings
from app.workflows import admin_account_workflow as workflow

from test_wp30_release_phase0 import db, seed_issues, snapshot  # noqa: F401


def run(db, argv, *, answers=(), passwords=()):
    out = StringIO()
    prompts = []
    inputs, secrets = iter(answers), iter(passwords)
    def input_fn(prompt):
        prompts.append(prompt)
        return next(inputs)
    def getpass_fn(prompt):
        prompts.append(prompt)
        return next(secrets)
    status = main(argv, db=db, input_fn=input_fn, getpass_fn=getpass_fn, out=out)
    return status, out.getvalue(), prompts


def test_confirmation_defaults_to_no_and_yes_flag_bypasses_only_confirmation(db):
    before = snapshot(db)
    for answer in ["", "n", "no", "yes"]:
        status, output, prompts = run(db, ["client", "suspend", "1", "--reason", "test", "--json"], answers=[answer])
        assert status == 1 and json.loads(output)["result"] == "cancelled"
        assert prompts == ["続行しますか？ [y/N]"]
        assert snapshot(db) == before
    status, _, prompts = run(db, ["--yes", "client", "suspend", "1", "--reason", "test"])
    assert status == 0 and not prompts and not db.get(models.Client, 1).is_active


def test_client_create_show_list_every_mutation_and_temporary_password_once(db):
    status, output, prompts = run(db, ["client", "create", "UPPER", "--name", "New", "--email", "NEW@example.com", "--json"], answers=["y"])
    assert status == 0 and len(prompts) == 1
    created = json.loads(output)
    client_id = created["id"]
    assert created["username"] == "upper" and len(created["temporary_password"]) == 16
    assert output.count(created["temporary_password"]) == 1
    status, output, _ = run(db, ["client", "show", str(client_id), "--json"])
    assert status == 0 and json.loads(output)["must_change_password"]
    status, output, _ = run(db, ["client", "list", "--query", "UPPER", "--json"])
    assert status == 0 and [row["id"] for row in json.loads(output)] == [client_id]
    for command in ["suspend", "reactivate", "approve", "unlock", "sign-out", "reset-password", "reset-mfa"]:
        argv = ["client", command, str(client_id), "--yes", "--json"]
        if command == "suspend":
            argv += ["--reason", "Support request"]
        status, output, prompts = run(db, argv)
        assert status == 0 and not prompts
        result = json.loads(output)
        assert result["id"] == client_id
        if command.startswith("reset-"):
            assert len(result["temporary_password"]) == 16 and output.count(result["temporary_password"]) == 1
            assert result["temporary_password"] not in str([r.detail for r in audit.list_logs(db)])
    for status in ["active", "suspended", "pending", "locked"]:
        assert run(db, ["client", "list", "--status", status, "--json"])[0] == 0
    assert {r.action for r in audit.list_logs(db)} >= {"client." + suffix for suffix in (
        "create", "suspend", "reactivate", "approve", "unlock", "sign_out", "reset_password", "reset_mfa")}


def test_admin_create_first_defaults_owner_confirms_totp_and_outputs_key_once(db):
    out = StringIO()
    prompts = []
    def input_fn(prompt):
        prompts.append(prompt)
        setup = json.loads(out.getvalue().splitlines()[0])
        return pyotp.TOTP(setup["manual_entry_key"]).now()
    status = main(["admin", "create", "OWNER", "--yes", "--json"], db=db, input_fn=input_fn,
                  getpass_fn=lambda prompt: "longpassword123", out=out)
    assert status == 0 and prompts == ["6-digit code: "]
    setup, result = [json.loads(line) for line in out.getvalue().splitlines()]
    admin = admins.get_by_username(db, "owner")
    assert admin and admin.mfa_enabled and admins.permissions_for(db, admin) == ALL_PERMISSIONS
    assert result["mfa_enabled"] and setup["manual_entry_key"] in setup["otpauth_uri"]
    # Each is printed in its designated field once; the key also appears inside its URI.
    assert out.getvalue().count('"manual_entry_key"') == 1
    assert setup["manual_entry_key"] not in str([r.detail for r in audit.list_logs(db)])
    assert {r.action for r in audit.list_logs(db)} == {"admin.create", "admin.confirm_totp"}


def test_admin_create_explicit_presets_permissions_and_bad_code_leave_unusable_account(db):
    for preset in PRESETS:
        status, output, _ = run(db, ["admin", "create", preset, "--preset", preset, "--permission", "accounts.export", "--yes", "--json"],
                                answers=["not-a-code"], passwords=["longpassword123"] * 2)
        assert status == 1
        admin = admins.get_by_username(db, preset)
        assert not admin.mfa_enabled
        assert admins.permissions_for(db, admin) == PRESETS[preset] | {"accounts.export"}
        assert json.loads(output.splitlines()[-1])["result"] == "refused"
        assert audit.list_logs(db)[0].result == "refused"
    status, output, _ = run(db, ["admin", "create", "mismatch", "--yes", "--json"], passwords=["longpassword123", "differentpassword"])
    assert status == 1 and admins.get_by_username(db, "mismatch") is None


def test_admin_list_disable_enable_reset_grant_revoke_and_last_owner_refusal(db):
    first, _ = workflow.admin_create(db, "first", "longpassword123", permissions=PRESETS["owner"], actor="cli:test")
    status, output, _ = run(db, ["admin", "disable", "first", "--yes", "--json"])
    assert status == 1 and json.loads(output)["result"] == "refused" and first.is_active
    workflow.admin_create(db, "second", "longpassword123", permissions=PRESETS["owner"], actor="cli:test")
    for argv in [["admin", "disable", "first"], ["admin", "enable", "first"],
                 ["admin", "revoke", "first", "accounts.read", "health.read"],
                 ["admin", "grant", "first", "accounts.read", "health.read"], ["admin", "reset-mfa", "first"]]:
        status, output, prompts = run(db, [*argv, "--yes", "--json"])
        assert status == 0 and not prompts
        if argv[1] == "reset-mfa":
            password = json.loads(output)["temporary_password"]
            assert output.count(password) == 1
    status, output, _ = run(db, ["admin", "list", "--json"])
    assert status == 0 and len(json.loads(output)) == 2
    assert "password_hash" not in output and "totp_secret_encrypted" not in output
    status, _, _ = run(db, ["admin", "grant", "first", "typo", "--yes", "--json"])
    assert status == 1
    assert audit.list_logs(db)[0].result == "failed"


def without_audit(db):
    return {key: value for key, value in snapshot(db).items() if key != "admin_audit_logs"}


def test_health_check_changes_only_audit_and_repair_updates_data_with_one_commit(db):
    seed_issues(db)
    before = without_audit(db)
    statements = []
    def record(connection, cursor, statement, *args):
        statements.append(statement)
    sa.event.listen(db.bind, "before_cursor_execute", record)
    try:
        status, output, _ = run(db, ["health", "check", "--client", "1", "--json"])
    finally:
        sa.event.remove(db.bind, "before_cursor_execute", record)
    assert status == 0 and without_audit(db) == before
    assert all("admin_audit_logs" in sql for sql in statements if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")))
    result = json.loads(output)
    assert result["client_id"] == 1 and {row["audience"] for row in result["issues"]} == {"user", "admin"}
    commits = []
    sa.event.listen(db, "after_commit", lambda session: commits.append(True))
    status, output, _ = run(db, ["health", "repair", "--client", "1", "--yes", "--json"])
    assert status == 0 and len(commits) == 1
    actions = json.loads(output)["actions"]
    assert next(a["updated"] for a in actions if a["code"] == "duplicate_plan_lines") == 1
    assert db.query(models.MonthlyPlanLine).filter_by(is_active=True).count() == 1
    assert db.query(models.BudgetPlan).filter_by(client_id=1, is_default=True).count() == 1
    assert audit.list_logs(db)[0].action == "health.repair"


def test_health_all_clients_summary_includes_inactive_and_only_adds_audit(db):
    before = without_audit(db)
    status, output, _ = run(db, ["health", "check", "--all-clients", "--json"])
    assert status == 0 and {row["client_id"] for row in json.loads(output)} == {1, 2, 3}
    assert all("issues" not in row for row in json.loads(output))
    assert without_audit(db) == before
    with pytest.raises(SystemExit) as exc:
        run(db, ["health", "repair", "--all-clients", "--yes"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        run(db, ["health", "check", "--all-clients", "--client", "1"])
    assert without_audit(db) == before


def test_health_single_client_caps_sample_items_but_preserves_count(db):
    seed_issues(db)
    for i in range(25):
        db.add(models.Transaction(client_id=1, date=date(2026, 9, 21), description=f"Late {i}",
                                  amount_minor=100, created_at=datetime(2026, 10, 3)))
    db.commit()
    status, output, _ = run(db, ["health", "check", "--client", "1", "--json"])
    late = next(row for row in json.loads(output)["issues"] if row["code"] == "entries_in_a_closed_period")
    assert status == 0 and late["count"] == 26 and len(late["items"]) == 20


def test_settings_json_string_validation_and_audit_tail(db):
    for key, value, expected in [("registration_mode", '"approval"', "approval"),
                                  ("registration_mode", "closed", "closed"),
                                  ("login_lockout_threshold", "3", 3)]:
        status, output, _ = run(db, ["settings", "set", key, value, "--yes", "--json"])
        assert status == 0 and json.loads(output)[key]["value"] == expected
    for argv in [["settings", "get"], ["settings", "get", "registration_mode"]]:
        status, output, _ = run(db, [*argv, "--json"])
        assert status == 0 and json.loads(output)["registration_mode"]["value"] == "closed"
    assert run(db, ["settings", "set", "login_lockout_threshold", "true", "--yes", "--json"])[0] == 1
    assert settings.get(db, "login_lockout_threshold") == 3
    status, output, _ = run(db, ["audit", "tail", "--action", "settings.", "--limit", "2", "--json"])
    assert status == 0 and len(json.loads(output)) == 2
    assert all(row["action"] == "settings.set" and row["actor"].startswith("cli:") for row in json.loads(output))
    status, output, _ = run(db, ["settings", "get", "unknown", "--json"])
    assert status == 1 and json.loads(output)["result"] == "failed"


@pytest.mark.parametrize("argv", [["client", "show", "999"], ["admin", "disable", "missing", "--yes"],
                                   ["health", "check", "--client", "999"]])
def test_missing_targets_produce_readable_errors(db, argv):
    status, output, _ = run(db, [*argv, "--json"])
    assert status == 1 and json.loads(output)["message"]


def _last_actor(db):
    return db.query(models.AdminAuditLog).order_by(models.AdminAuditLog.id.desc()).first().actor


def test_audit_actor_is_the_host_operator_passed_by_am_admin(db, monkeypatch):
    monkeypatch.setenv("AM_CLI_OPERATOR", "ops-user")
    assert run(db, ["settings", "set", "registration_mode", "approval", "--yes"])[0] == 0
    assert _last_actor(db) == "cli:ops-user"


@pytest.mark.parametrize("value", ["", "two words", "x;rm -rf", "a" * 65, "名前"])
def test_unsafe_or_missing_operator_falls_back_to_the_process_user(db, monkeypatch, value):
    monkeypatch.setenv("AM_CLI_OPERATOR", value)
    monkeypatch.setattr("app.admin.cli.getpass.getuser", lambda: "container-user")
    assert run(db, ["settings", "set", "registration_mode", "open", "--yes"])[0] == 0
    assert _last_actor(db) == "cli:container-user"


def test_table_output_contains_headers_and_rows(db):
    status, output, _ = run(db, ["client", "list"])
    assert status == 0 and "username" in output and "transaction_count" in output
    assert "dev" in output and "inactive" in output
