"""One-off manual credit grant. Run inside the backend container:

    docker-compose exec backend python -m app.scripts.grant_credits <user_id> <amount> \
        [--reason "..."]

Sync-only: uses the psycopg2 SyncSession (same one Celery tasks use) since
there's no event loop here — never import AsyncSession into this module.
"""

import argparse
import sys
from uuid import UUID

import structlog

from app.models.user import User
from app.services.billing_service import sync_grant_credits
from app.tasks.video_pipeline import SyncSession

logger = structlog.get_logger()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually grant credits to a user's account.")
    parser.add_argument("user_id", type=UUID, help="User UUID")
    parser.add_argument("amount", type=int, help="Credits to grant (must be positive)")
    parser.add_argument(
        "--reason", default="Manual admin grant", help="Reason recorded on the ledger entry"
    )
    args = parser.parse_args()

    if args.amount <= 0:
        print(f"error: amount must be positive, got {args.amount}", file=sys.stderr)
        sys.exit(1)

    db = SyncSession()
    try:
        user = db.get(User, args.user_id)
        if user is None:
            print(f"error: no user with id {args.user_id}", file=sys.stderr)
            sys.exit(1)
        if user.deleted_at is not None:
            print(f"error: user {args.user_id} is soft-deleted, refusing to grant", file=sys.stderr)
            sys.exit(1)

        tx, balance_before, balance_after = sync_grant_credits(
            db, args.user_id, args.amount, args.reason
        )
        logger.info(
            "manual_credit_grant",
            user_id=str(args.user_id),
            amount=args.amount,
            reason=args.reason,
            transaction_id=str(tx.id),
        )
        print(f"user:        {user.email} ({user.id})")
        print(f"transaction: {tx.id}")
        print(f"balance:     {balance_before} -> {balance_after}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
