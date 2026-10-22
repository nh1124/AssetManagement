"""Inspect data health issues, or apply administrator repairs for one client.

Run inside the backend container:

    python -m app.maintenance.data_health --client-id 1
    python -m app.maintenance.data_health --all-clients
    python -m app.maintenance.data_health --client-id 1 --apply

Without --apply this command only reads. Each client has a JSON summary followed
by issue JSON lines (including at most 20 sampled items per issue).
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import Session

from .. import models
from ..services.data_health_service import check_data_health, repair_data_health


def main(argv: list[str] | None = None, *, db: Session | None = None) -> int:
    from ..database import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    clients = parser.add_mutually_exclusive_group(required=True)
    clients.add_argument("--client-id", type=int)
    clients.add_argument("--all-clients", action="store_true")
    parser.add_argument("--apply", action="store_true", help="apply repairs for --client-id only")
    args = parser.parse_args(argv)
    if args.apply and args.client_id is None:
        parser.error("--apply requires --client-id")

    owned = db is None
    if owned:
        db = SessionLocal()
    try:
        if args.client_id is not None:
            client = db.get(models.Client, args.client_id)
            if client is None:
                parser.error(f"client {args.client_id} does not exist")
            rows = [client]
        else:
            rows = db.query(models.Client).filter_by(is_active=True).order_by(models.Client.id).all()
        with db.no_autoflush:
            for client in rows:
                if args.apply:
                    result = repair_data_health(db, client.id)
                    print(json.dumps({"client_id": client.id, "actions": result["actions"]}, ensure_ascii=False))
                    health = result["health"]
                else:
                    health = check_data_health(db, client.id)
                print(json.dumps({"client_id": client.id, **{key: health[key] for key in
                                 ("status", "total_issues", "repairable_groups")}}, ensure_ascii=False))
                for issue in health["issues"]:
                    if issue["count"] > 0:
                        print(json.dumps({"client_id": client.id, **{key: issue[key] for key in
                                         ("audience", "severity", "code", "title", "count")},
                                          "items": issue["items"][:20]}, ensure_ascii=False))
    finally:
        if owned:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
