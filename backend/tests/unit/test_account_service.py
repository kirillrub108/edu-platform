"""Pure parts of the account lifecycle: the tombstone definition, the restore
window arithmetic, and the two signed links."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.constants import ANONYMIZED_EMAIL_DOMAIN, PROFILE_DELETED_USER_NAME
from app.models.user import User, UserRole
from app.services.account_service import (
    anonymize_user_fields,
    generate_release_token,
    generate_restore_token,
    is_anonymized,
    restore_deadline,
    verify_release_token,
    verify_restore_token,
    within_restore_window,
)
from app.services.auth_service import hash_password, verify_password

pytestmark = pytest.mark.unit


def _deleted_user(**overrides) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        email="teacher@example.com",
        hashed_password=hash_password("correct horse"),
        full_name="Иван Петров",
        bio="Преподаю математику",
        role=UserRole.teacher,
        is_active=False,
        avatar_image_path="avatars/x/y.webp",
        avatar_external_url="https://lh3.googleusercontent.com/a/z",
        pdn_consent_at=datetime.now(timezone.utc),
        terms_accepted_at=datetime.now(timezone.utc),
        marketing_consent=True,
        marketing_consent_at=datetime.now(timezone.utc),
        consent_policy_version="2026-08-29",
        consent_ip="203.0.113.7",
        deleted_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return User(**defaults)


# ── tombstone ────────────────────────────────────────────────────────────────


def test_anonymize_clears_every_personal_field() -> None:
    user = _deleted_user()
    original_password = "correct horse"
    deleted_at = user.deleted_at

    anonymize_user_fields(user)

    assert user.email == f"deleted+{user.id}@{ANONYMIZED_EMAIL_DOMAIN}"
    assert user.full_name == PROFILE_DELETED_USER_NAME
    assert user.bio is None
    assert user.avatar_image_path is None
    assert user.avatar_external_url is None
    assert user.pdn_consent_at is None
    assert user.terms_accepted_at is None
    assert user.marketing_consent is False
    assert user.marketing_consent_at is None
    assert user.consent_policy_version is None
    assert user.consent_ip is None
    assert user.is_active is False
    # deleted_at survives: the row stays soft-deleted, it is just no longer personal.
    assert user.deleted_at == deleted_at
    # The old password must no longer verify against the tombstoned hash.
    assert not verify_password(original_password, user.hashed_password)


def test_anonymize_is_idempotent() -> None:
    user = _deleted_user()
    anonymize_user_fields(user)
    snapshot = (user.email, user.full_name, user.hashed_password)

    anonymize_user_fields(user)

    assert (user.email, user.full_name, user.hashed_password) == snapshot


def test_is_anonymized_detects_the_tombstone() -> None:
    user = _deleted_user()
    assert is_anonymized(user) is False
    anonymize_user_fields(user)
    assert is_anonymized(user) is True


def test_anonymize_has_no_side_effects_on_the_session() -> None:
    """The function must stay pure: the sync purge task calls it with a
    psycopg2 Session and the async release path with an AsyncSession."""
    user = _deleted_user()
    anonymize_user_fields(user)  # no db, no storage, no exception


# ── restore window ───────────────────────────────────────────────────────────


def test_restore_deadline_is_thirty_days_after_deletion() -> None:
    deleted_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    user = _deleted_user(deleted_at=deleted_at)
    assert restore_deadline(user) == deleted_at + timedelta(days=30)


def test_restore_deadline_none_for_live_account() -> None:
    assert restore_deadline(_deleted_user(deleted_at=None)) is None


def test_window_open_then_closed() -> None:
    fresh = _deleted_user(deleted_at=datetime.now(timezone.utc) - timedelta(days=1))
    stale = _deleted_user(deleted_at=datetime.now(timezone.utc) - timedelta(days=31))
    assert within_restore_window(fresh) is True
    assert within_restore_window(stale) is False


def test_naive_deleted_at_is_treated_as_utc() -> None:
    """Postgres can hand back a naive datetime depending on the driver path;
    comparing it against an aware now() would raise instead of answering."""
    user = _deleted_user(deleted_at=datetime.now(timezone.utc).replace(tzinfo=None))
    assert within_restore_window(user) is True


# ── signed links ─────────────────────────────────────────────────────────────


def test_restore_token_roundtrip() -> None:
    user_id = str(uuid.uuid4())
    assert verify_restore_token(generate_restore_token(user_id)) == user_id


def test_release_token_roundtrip() -> None:
    user_id = str(uuid.uuid4())
    assert verify_release_token(generate_release_token(user_id)) == user_id


def test_tokens_do_not_cross_salts() -> None:
    """Separate salts, so a restore link can never be replayed as a release link
    — one is recoverable, the other destroys the account permanently."""
    user_id = str(uuid.uuid4())
    with pytest.raises(ValueError):
        verify_release_token(generate_restore_token(user_id))
    with pytest.raises(ValueError):
        verify_restore_token(generate_release_token(user_id))


def test_tampered_token_rejected() -> None:
    token = generate_restore_token(str(uuid.uuid4()))
    with pytest.raises(ValueError):
        verify_restore_token(token[:-3] + "aaa")
