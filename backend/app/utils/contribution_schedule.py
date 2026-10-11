"""Parsing for the contribution_schedule query parameter.

Lives in utils because three features read the same parameter - goals, the
roadmap and the Monte Carlo workflow - and they must agree on what a malformed
value means. The 400s are part of that agreement, so they stay here with the
parse rather than being re-raised by each caller.
"""
from __future__ import annotations

import json

from fastapi import HTTPException


def parse_contribution_schedule(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid contribution_schedule JSON") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="contribution_schedule must be a list")
    return [item for item in value if isinstance(item, dict)]
