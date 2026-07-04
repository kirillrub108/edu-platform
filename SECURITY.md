# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via **GitHub Security Advisories**:
[**Security → Report a vulnerability**](../../security/advisories/new) on this
repository. That opens a private thread with the maintainers.

If you prefer email, use the maintainer contact listed on the GitHub profile
that owns this repo. (No contact address is committed to the repository to keep
it out of spam-harvesting bots.)

When reporting, please include:

- affected component (backend route, Celery task, frontend, infra config…);
- a minimal reproduction or proof-of-concept;
- impact (what an attacker gains) and any suggested fix.

We aim to acknowledge a report within a few days and to agree on a disclosure
timeline before any details go public.

## Scope

This is a self-hostable project. The most security-relevant areas:

- **Auth** — httpOnly-cookie sessions + double-submit CSRF, Argon2id password
  hashing, refresh-token rotation with reuse detection
  (`backend/app/services/auth_service.py`, see `docs/AUTH_FLOW.md`).
- **Signed static delivery** — HMAC-signed `/files/*` URLs
  (`services/signed_url_service.py`).
- **Payments webhook** — YooKassa notifications are verified by re-fetching the
  payment from YooKassa's API; the notification body is never trusted
  (`services/yookassa_service.py`).
- **AI-operation gating** — every LLM/vision/TTS endpoint sits behind an
  email-verification guard, CI-enforced (`tests/integration/test_ai_gating_guard.py`).

Known, already-tracked weaknesses live in
[`docs/KNOWN_PROBLEMS.md`](docs/KNOWN_PROBLEMS.md) — check there before reporting
something that may already be documented.

## Operator responsibilities

This repository ships **templates**, not live secrets:

- Copy `.env.example` → `.env` (dev) / `.env.prod.example` → `.env.prod` (prod)
  and fill real values. The filled files are git-ignored — never commit them.
- Generate a strong `SECRET_KEY` (`openssl rand -hex 32`); production rejects a
  weak one at startup.
- Set strong `POSTGRES_PASSWORD` / `REDIS_PASSWORD`; keep provider API keys
  (Polza / Yandex / YooKassa / Resend) out of version control.
- In production, `CORS_ORIGINS` must be an explicit allowlist — a wildcard `*`
  is a hard startup error (cookie auth).
