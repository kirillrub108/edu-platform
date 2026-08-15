"""One-off manual credit grant. Run inside the backend container:

    docker-compose exec backend python -m app.scripts.grant_credits <email> <amount> \
        [--reason "..."]

Sync-only: uses the psycopg2 SyncSession (same one Celery tasks use) since
there's no event loop here — never import AsyncSession into this module.
"""

import argparse
import sys

import structlog
from sqlalchemy import func, select

from app.models.user import User
from app.services.billing_service import sync_grant_credits
from app.tasks.video_pipeline import SyncSession

logger = structlog.get_logger()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually grant credits to a user's account.")
    parser.add_argument("email", type=str, help="User email")
    parser.add_argument("amount", type=int, help="Credits to grant (must be positive)")
    parser.add_argument(
        "--reason", default="Manual admin grant", help="Reason recorded on the ledger entry"
    )
    args = parser.parse_args()

    if args.amount <= 0:
        print(f"error: amount must be positive, got {args.amount}", file=sys.stderr)
        sys.exit(1)

    email = args.email.strip().lower()

    db = SyncSession()
    try:
        # select (not db.get) so the global soft-delete filter excludes deleted users.
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None or not user.is_active:
            print(f"error: no active user with email {args.email!r}", file=sys.stderr)
            sys.exit(1)

        tx, balance_before, balance_after = sync_grant_credits(
            db, user.id, args.amount, args.reason
        )
        logger.info(
            "manual_credit_grant",
            user_id=str(user.id),
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
