"""Rebuild AI audit rows from the backend's JSON log (WP34).

The audit of every MCP request began with WP34. For MCP requests made before it,
the administrator's log still holds what happened: request.start / request.end
and one db.change line per committed row, all carrying the request id. This
rebuilds the audit row each such request would have had, through the same
ai_policy_service.record_mcp_operation the gateway uses, marked
restored_from="backend_log". Request bodies were never logged, so restored rows
have none. Requests that already have an audit row are skipped, so a second run
adds nothing.

Dry-run by default. Run inside the backend container, feeding it the log:

    docker logs finance-backend --since 2026-10-24T00:00:00 2>&1 \
      | docker exec -i finance-backend python -m app.maintenance.restore_ai_audit --client-id 2

Add --apply to write the rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from app.database import SessionLocal
from app.services import ai_policy_service
from app.services.ai_policy_service import McpRequestFacts

_CHANGE_KEYS = ("table", "op", "pk", "values", "changes", "rows")


@dataclass
class _Request:
    start: dict
    end: dict | None = None
    changes: list[dict] = field(default_factory=list)


def _utc_naive(timestamp: str) -> datetime:
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def collect(lines: Iterable[str], client_id: int) -> list[_Request]:
    """The MCP requests this client made, in the order they started, with their outcome and rows."""
    requests: dict[str, _Request] = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("channel") != "mcp" or entry.get("component", "backend") != "backend":
            continue
        request_id = entry.get("request_id")
        event = entry.get("event")
        if not request_id:
            continue
        if event == "request.start" and entry.get("actor_client_id") == client_id:
            requests[request_id] = _Request(start=entry)
        elif request_id in requests:
            if event == "request.end":
                requests[request_id].end = entry
            elif event == "db.change":
                requests[request_id].changes.append({key: entry[key] for key in _CHANGE_KEYS if key in entry})
    return [
        request for request in requests.values()
        if request.end is not None
        and ai_policy_service.mcp_request_is_operation(request.start.get("method", ""), request.start.get("path", ""))
    ]


def facts_of(request: _Request) -> McpRequestFacts:
    start, end = request.start, request.end or {}
    return McpRequestFacts(
        method=start.get("method", ""),
        path=start.get("path", ""),
        status=int(end.get("status", 500)),
        query=start.get("query", ""),
        duration_ms=end.get("duration_ms"),
        request_id=start.get("request_id"),
        correlation_id=start.get("correlation_id"),
        mcp_client_id=start.get("mcp_client_id"),
        tool_name=start.get("mcp_tool"),
        ip_address=start.get("client_ip") or None,
        user_agent=start.get("user_agent"),
        changes=request.changes,
        created_at=_utc_naive(start["ts"]),
        restored_from="backend_log",
    )


def restore(db, client_id: int, lines: Iterable[str], *, apply: bool) -> Counter:
    requests = collect(lines, client_id)
    done = ai_policy_service.audited_request_ids(db, client_id, [request.start["request_id"] for request in requests])
    tally: Counter = Counter()
    for request in requests:
        if request.start["request_id"] in done:
            tally["already_audited"] += 1
            continue
        facts = facts_of(request)
        resource, action, _, _ = ai_policy_service.describe_mcp_request(facts.method, facts.path)
        tally[f"{resource}:{action}:{facts.status}"] += 1
        if apply:
            ai_policy_service.record_mcp_operation(db, client_id, facts)
            tally["written"] += 1
    return tally


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="write the rows (default: report only)")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        tally = restore(db, args.client_id, sys.stdin, apply=args.apply)
    finally:
        db.close()
    for key, count in sorted(tally.items()):
        print(f"{count:5d}  {key}")
    if not args.apply:
        print("dry run: nothing written (add --apply)")


if __name__ == "__main__":
    main()
