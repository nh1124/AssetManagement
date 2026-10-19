from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.domain.transfer import (
    EXPORT_VERSION,
    _as_int,
    _canonical_json,
    _normalize_for_checksum,
    _sha256,
    _table_checksums,
    assert_imported_journal_invariant,
    build_manifest,
    data_counts,
    parse_date,
    parse_datetime,
    remap_action_target_id,
    remap_nested_ids,
    row_fields,
    validate_import_payload,
)


def _checksum_sample(amount=12.5):
    return {
        "accounts": [
            {"id": 2, "name": "財布", "balance": 12.0, "note": None,
             "nested": {"z": [1.0, 1.25, None], "a": {"enabled": True}}},
            {"name": "bank", "id": 1, "balance": -0.0},
        ],
        "transactions": [
            {"id": 10, "date": date(2026, 10, 5), "amount": amount,
             "created_at": datetime(2026, 10, 5, 6, 7, 8, 9000)},
        ],
        "journal_entries": [
            {"id": 20, "transaction_id": 10, "account_id": 1,
             "debit": 12.5, "credit": None},
            {"id": 21, "transaction_id": 10, "account_id": 2,
             "debit": 0.0, "credit": 12.5},
        ],
    }


# Captured from the router at 2f60437, before extracting the file format rules.
EMPTY_TABLE_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
SAMPLE_DIGEST = "b0af7658403f3086011bd58bd60d0e583d974b3fd2530c69b845a2f300682108"
# Quick templates left the format (E4); the sample data byte digest stays fixed.
PAYLOAD_DIGEST = "795ed891cd9931a0a4fb37d0ea18e2089a13cec8454a698d4c10d7036ad5f2a6"
# The same sample as exported while quick_templates was still a collection.
PRE_E4_PAYLOAD_DIGEST = "8ce363d73785ffbc2a3c6d9e1b53da7bbda72874400f841d84c1c4ecba0e5d14"
TABLE_DIGESTS = {
    "accounts": "69abf8cb7c47317e9cdeb2200e9bd1157c5b0c09fd880290e46e561fd78a51ee",
    "products": EMPTY_TABLE_DIGEST,
    "product_depreciations": EMPTY_TABLE_DIGEST,
    "simulation_configs": EMPTY_TABLE_DIGEST,
    "registry_entries": EMPTY_TABLE_DIGEST,
    "transaction_batches": EMPTY_TABLE_DIGEST,
    "life_events": EMPTY_TABLE_DIGEST,
    "life_event_links": EMPTY_TABLE_DIGEST,
    "life_scenarios": EMPTY_TABLE_DIGEST,
    "scenario_contribution_plans": EMPTY_TABLE_DIGEST,
    "household_members": EMPTY_TABLE_DIGEST,
    "life_event_conditions": EMPTY_TABLE_DIGEST,
    "transactions": "e1f953879ca1d2c393b78eeb1caa65ea6d67a8a75ff0ee24b5813cb2cf40a458",
    "journal_entries": "206b4dd4f44356a6bc5662506bbd56268e8b123aa8255b7aebb1495e13f44e29",
    "budget_plans": EMPTY_TABLE_DIGEST,
    "monthly_plan_lines": EMPTY_TABLE_DIGEST,
    "period_reviews": EMPTY_TABLE_DIGEST,
    "period_closes": EMPTY_TABLE_DIGEST,
    "monthly_actions": EMPTY_TABLE_DIGEST,
    "capsules": EMPTY_TABLE_DIGEST,
    "capsule_drawdowns": EMPTY_TABLE_DIGEST,
    "capsule_funding_sources": EMPTY_TABLE_DIGEST,
    "capsule_rules": EMPTY_TABLE_DIGEST,
    "goal_event_earmarks": EMPTY_TABLE_DIGEST,
    "fx_tracked_currencies": EMPTY_TABLE_DIGEST,
    "exchange_rates": EMPTY_TABLE_DIGEST,
    "goal_budget_reflections": EMPTY_TABLE_DIGEST,
}
SAMPLE_COUNTS = {
    key: {"accounts": 2, "transactions": 1, "journal_entries": 2}.get(key, 0)
    for key in TABLE_DIGESTS
}


def test_checksums_match_existing_backups_byte_for_byte():
    sample = _checksum_sample()
    assert _canonical_json(sample) == (
        '{"accounts":[{"balance":12,"id":2,"name":"財布","nested":{"a":{"enabled":true},'
        '"z":[1,1.25,null]},"note":null},{"balance":0,"id":1,"name":"bank"}],'
        '"journal_entries":[{"account_id":1,"credit":null,"debit":12.5,"id":20,"transaction_id":10},'
        '{"account_id":2,"credit":12.5,"debit":0,"id":21,"transaction_id":10}],'
        '"transactions":[{"amount":12.5,"created_at":"2026-10-05 06:07:08.009000",'
        '"date":"2026-10-05","id":10}]}'
    )
    assert _sha256(sample) == SAMPLE_DIGEST
    checksums = _table_checksums(sample)
    assert checksums == TABLE_DIGESTS
    assert _sha256({"data": sample, "checksums": checksums}) == PAYLOAD_DIGEST


def test_export_version_is_26_with_goal_earmarks():
    # Stories carry ownership and lineage; branch choices no longer exist.
    assert EXPORT_VERSION == 26


@pytest.mark.parametrize("value, expected", [
    pytest.param(date(2026, 10, 5), date(2026, 10, 5), id="date-stays-date"),
    pytest.param(datetime(2026, 10, 5, 6, 7), datetime(2026, 10, 5, 6, 7), id="datetime-stays-datetime"),
    pytest.param(12.0, 12, id="integral-float-becomes-int"),
    pytest.param(None, None, id="null"),
    pytest.param({"z": {"amount": 12.0}, "a": None}, {"z": {"amount": 12}, "a": None}, id="nested-dict"),
    pytest.param([12.0, 12.5, None, {"ids": [1.0]}], [12, 12.5, None, {"ids": [1]}], id="nested-list"),
])
def test_checksum_normalization_preserves_current_representations(value, expected):
    actual = _normalize_for_checksum(value)
    assert actual == expected
    assert type(actual) is type(expected)
    if isinstance(actual, dict):
        assert list(actual) == list(value)


@pytest.mark.parametrize("parser, value, expected", [
    pytest.param(parse_date, "2026-10-05", date(2026, 10, 5), id="date-string"),
    pytest.param(parse_date, date(2026, 10, 5), date(2026, 10, 5), id="date-object"),
    pytest.param(parse_date, "", None, id="date-empty"),
    pytest.param(parse_date, None, None, id="date-null"),
    pytest.param(parse_datetime, "2026-10-05T06:07:08", datetime(2026, 10, 5, 6, 7, 8), id="datetime-string"),
    pytest.param(parse_datetime, datetime(2026, 10, 5, 6, 7), datetime(2026, 10, 5, 6, 7), id="datetime-object"),
    pytest.param(parse_datetime, date(2026, 10, 5), datetime(2026, 10, 5), id="date-to-midnight"),
    pytest.param(parse_datetime, "", None, id="datetime-empty"),
    pytest.param(parse_datetime, None, None, id="datetime-null"),
    pytest.param(_as_int, "12", 12, id="integer-string"),
    pytest.param(_as_int, "", None, id="integer-empty"),
    pytest.param(_as_int, None, None, id="integer-null"),
    pytest.param(_as_int, "bad", None, id="malformed-integer"),
    pytest.param(_as_int, {}, None, id="integer-type-error"),
    pytest.param(_as_int, 12.9, 12, id="float-truncates"),
    pytest.param(_as_int, 0, 0, id="zero-id"),
])
def test_parsers_keep_current_values_and_empty_handling(parser, value, expected):
    assert parser(value) == expected


@pytest.mark.parametrize("parser, value", [
    pytest.param(parse_date, "bad", id="malformed-date"),
    pytest.param(parse_datetime, "bad", id="malformed-datetime"),
    pytest.param(parse_date, datetime(2026, 10, 5), id="datetime-is-not-a-date-string"),
])
def test_malformed_dates_raise_instead_of_becoming_null(parser, value):
    with pytest.raises(ValueError):
        parser(value)


def test_manifest_uses_only_supplied_metadata_and_format_checksums():
    sample = _checksum_sample()
    assert build_manifest(7, sample, "2026-10-05T06:07:08", "revision-123") == {
        "export_version": 26,
        "exported_at": "2026-10-05T06:07:08",
        "application": "AssetManagement",
        "alembic_revision": "revision-123",
        "client_id": 7,
        "counts": SAMPLE_COUNTS,
        "checksums": TABLE_DIGESTS,
        "payload_checksum": PAYLOAD_DIGEST,
    }


def test_export_rows_serialize_dates_and_keep_other_values():
    source = SimpleNamespace(day=date(2026, 10, 5), stamp=datetime(2026, 10, 5, 6, 7), amount=12.0, note=None)
    assert row_fields(source, ["stamp", "day", "amount", "note"]) == {
        "stamp": "2026-10-05T06:07:00", "day": "2026-10-05", "amount": 12.0, "note": None,
    }


def test_valid_payload_accepts_balanced_journal_and_matching_manifest():
    sample = _checksum_sample()
    manifest = {"counts": SAMPLE_COUNTS, "checksums": TABLE_DIGESTS, "payload_checksum": PAYLOAD_DIGEST}
    assert validate_import_payload(sample, 26, manifest) == {
        "status": "valid", "error_count": 0, "warning_count": 0,
        "counts": SAMPLE_COUNTS, "issues": [],
    }


def test_a_manifest_from_before_quick_templates_were_removed_still_verifies():
    sample = _checksum_sample()
    # A v23 manifest names the collections of its day, not those added or retired since.
    added = {"fx_tracked_currencies", "scenario_contribution_plans", "goal_event_earmarks"}
    retired = ("recurring_transactions", "quick_templates", "life_scenario_account_returns", "milestones", "simulation_scenarios", "goal_baselines")
    checksums = {**{key: value for key, value in TABLE_DIGESTS.items() if key not in added}, **dict.fromkeys(retired, EMPTY_TABLE_DIGEST)}
    counts = {**{key: value for key, value in SAMPLE_COUNTS.items() if key not in added}, **dict.fromkeys(retired, 0)}
    manifest = {"counts": counts, "checksums": checksums, "payload_checksum": PRE_E4_PAYLOAD_DIGEST}
    assert [row["code"] for row in validate_import_payload(sample, 23, manifest)["issues"]] == ["older_version"]
    # Rows in the retired collection are not reported, and never counted.
    result = validate_import_payload({"quick_templates": [{"id": 1, "default_from_account_id": 99}]}, 26)
    assert (result["issues"], "quick_templates" in result["counts"]) == ([], False)


@pytest.mark.parametrize("data, version, manifest, expected", [
    pytest.param({"unknown": []}, 26, None, {
        "severity": "warning", "code": "unknown_collection",
        "detail": "This collection is not imported by this application version.", "collection": "unknown",
    }, id="unknown-collection"),
    pytest.param({}, 27, None, {
        "severity": "error", "code": "unsupported_version",
        "detail": "Export version 27 is newer than supported version 26.",
    }, id="unsupported-version"),
    pytest.param({}, 7, None, {
        "severity": "warning", "code": "older_version",
        "detail": "Export version 7 will be imported with compatibility defaults.",
    }, id="older-version"),
    pytest.param({"accounts": [{}]}, 26, None, {
        "severity": "error", "code": "missing_id", "detail": "Row 0 is missing a valid id.",
        "collection": "accounts", "field": "id",
    }, id="missing-id"),
    pytest.param({"accounts": [{"id": 1}, {"id": "1"}]}, 26, None, {
        "severity": "error", "code": "duplicate_id", "detail": "Duplicate id 1.",
        "collection": "accounts", "item_id": 1, "field": "id",
    }, id="duplicate-id"),
    pytest.param({"capsule_rules": [{"id": 1, "capsule_id": "bad"}]}, 26, None, {
        "severity": "error", "code": "invalid_reference", "detail": "capsule_id is not a valid integer id.",
        "collection": "capsule_rules", "item_id": 1, "field": "capsule_id",
    }, id="invalid-reference"),
    pytest.param({"capsule_rules": [{"id": 1}]}, 26, None, {
        "severity": "error", "code": "missing_reference", "detail": "capsule_id is required.",
        "collection": "capsule_rules", "item_id": 1, "field": "capsule_id",
    }, id="required-reference"),
    pytest.param({"transactions": [{"id": 10, "amount": 12.5}]}, 26, None, {
        "severity": "error", "code": "journal_entries_missing",
        "detail": "Each transaction must have at least two journal entries.",
        "collection": "transactions", "item_id": 10,
    }, id="missing-journal"),
    pytest.param(_checksum_sample(amount="bad"), 26, None, {
        "severity": "error", "code": "journal_amount_invalid",
        "detail": "Transaction and journal amounts must be numeric.", "collection": "transactions", "item_id": 10,
    }, id="nonnumeric-amount"),
    pytest.param(_checksum_sample(amount=13), 26, None, {
        "severity": "error", "code": "journal_unbalanced",
        "detail": "Journal totals must satisfy debit=credit=amount; got debit=12.5, credit=12.5, amount=13.0.",
        "collection": "transactions", "item_id": 10,
    }, id="unbalanced-journal"),
    pytest.param({"monthly_plan_lines": [{"id": 1, "target_type": "product", "target_id": 99}]}, 26, None, {
        "severity": "error", "code": "missing_reference", "detail": "target_id points to missing products id 99.",
        "collection": "monthly_plan_lines", "item_id": 1, "field": "target_id",
    }, id="dangling-plan-target"),
    pytest.param({}, 26, {"counts": {"accounts": 1}}, {
        "severity": "error", "code": "count_mismatch", "detail": "Manifest count 1 does not match payload count 0.",
        "collection": "accounts",
    }, id="count-mismatch"),
    pytest.param({}, 26, {"checksums": {"accounts": "bad"}}, {
        "severity": "warning", "code": "checksum_mismatch",
        "detail": "Collection checksum does not match the export manifest. This can happen with older exports after JSON number normalization.",
        "collection": "accounts",
    }, id="checksum-mismatch"),
    pytest.param({"life_scenarios": [{"id": 1, "name": "本案", "is_goal": True}], "life_events": [
        {"id": 1, "scenario_id": 1, "lineage": "00000000-0000-4000-8000-000000000001"},
        {"id": 2, "scenario_id": 1, "lineage": "00000000-0000-4000-8000-000000000002"}], "life_event_links": [
        {"id": 1, "from_event_id": 1, "to_event_id": 2, "kind": "after", "adopted": "false"},
    ]}, 26, None, {
        "severity": "error", "code": "invalid_event_link",
        "detail": "Event link adoption must be a boolean.",
        "collection": "life_event_links", "item_id": 1,
    }, id="non-boolean-adoption"),
    pytest.param({}, 26, {"payload_checksum": "bad"}, {
        "severity": "warning", "code": "payload_checksum_mismatch",
        "detail": "Payload checksum does not match the export manifest. This can happen with older exports after JSON number normalization.",
    }, id="payload-checksum-mismatch"),
])
def test_payload_validation_preserves_every_distinct_issue_message(data, version, manifest, expected):
    result = validate_import_payload(data, version, manifest)
    assert result["issues"] == [expected]
    is_error = expected["severity"] == "error"
    assert result["status"] == ("invalid" if is_error else "valid")
    assert result["error_count"] == int(is_error)
    assert result["warning_count"] == int(not is_error)


def test_legacy_optional_references_and_absent_version_still_validate():
    assert validate_import_payload({"accounts": [{"id": "1", "account_type": "asset", "parent_id": "bad"}]})["issues"] == []
    assert validate_import_payload({}, 0)["issues"] == []
    assert data_counts({"unknown": [{"id": 1}]}) == {key: 0 for key in TABLE_DIGESTS}


@pytest.mark.parametrize("amount, entries", [
    pytest.param(12.5, [{"debit": 12.5}, {"credit": 12.5}], id="two-legs"),
    pytest.param("12.5", [{"debit": "5"}, {"debit": 7.5}, {"credit": 12.5}], id="compound-entry"),
    pytest.param(None, [{"debit": None}, {"credit": None}], id="null-amounts-still-coerce-to-zero"),
    pytest.param(0.01, [{"debit": 0.01}, {"credit": 0.02}], id="current-absolute-tolerance"),
])
def test_imported_journal_accepts_current_balanced_totals(amount, entries):
    assert assert_imported_journal_invariant(10, amount, entries) is None


@pytest.mark.parametrize("amount, entries, message", [
    pytest.param(12.5, [], "Transaction 10 has fewer than two journal entries", id="no-legs"),
    pytest.param(12.5, [{"debit": 12.5}], "Transaction 10 has fewer than two journal entries", id="one-leg"),
    pytest.param(12.5, [{"debit": 12.5}, {"credit": 12}],
                 "Transaction 10 journal totals do not satisfy debit=credit=amount", id="sides-disagree"),
    pytest.param(13, [{"debit": 12.5}, {"credit": 12.5}],
                 "Transaction 10 journal totals do not satisfy debit=credit=amount", id="amount-disagrees"),
])
def test_imported_journal_refuses_missing_or_unbalanced_entries(amount, entries, message):
    with pytest.raises(ValueError) as error:
        assert_imported_journal_invariant(10, amount, entries)
    assert str(error.value) == message


def test_nested_id_remapping_preserves_unknown_ids_and_original_payload():
    original = {
        "account_id": "1", "capsule_id": "99", "unmapped_id": 1,
        "nested": [{"account_id": 2, "deeper": {"capsule_id": 3}},
                   {"account_id": "bad"}, None, 1],
    }
    assert remap_nested_ids(original, {"account_id": {1: 101, 2: 102}, "capsule_id": {3: 103}}) == {
        "account_id": 101, "capsule_id": "99", "unmapped_id": 1,
        "nested": [{"account_id": 102, "deeper": {"capsule_id": 103}},
                   {"account_id": "bad"}, None, 1],
    }
    assert original["account_id"] == "1"
    assert original["nested"][0] == {"account_id": 2, "deeper": {"capsule_id": 3}}


@pytest.mark.parametrize("item, expected", [
    pytest.param({"kind": "set_budget", "target_id": "1"}, 101, id="budget-account"),
    pytest.param({"kind": "stop_auto_transaction", "target_id": 1}, 201, id="recurring"),
    pytest.param({"kind": "change_capsule_contribution", "target_id": 1}, 301, id="capsule"),
    pytest.param({"kind": "set_budget", "target_id": 99}, 99, id="unmapped-target"),
    pytest.param({"kind": "unknown", "target_id": "1"}, 1, id="unknown-kind"),
    pytest.param({"kind": "set_budget", "target_id": "bad"}, None, id="malformed-target"),
    pytest.param({"kind": "set_budget"}, None, id="missing-target"),
])
def test_action_target_remapping_follows_kind_and_preserves_unknown_ids(item, expected):
    maps = {"account_id": {1: 101}, "registry_entry_id": {1: 201}, "capsule_id": {1: 301}, "life_event_id": {1: 401}}
    assert remap_action_target_id(item, maps) == expected
